"""Servicio de aplicación: une agentes, seguridad, costos y observabilidad.

La API REST y el servidor MCP son adaptadores delgados sobre este servicio:
ninguno de los dos sabe cómo razonan los agentes, y los agentes no saben si
los llamó un navegador o un host MCP.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from dataclasses import dataclass

from app.agents.hr_agent import HrAgent
from app.agents.runtime import RunContext
from app.agents.summary_agent import SummaryAgent
from app.agents.vacation_agent import VacationAgent
from app.clock import Clock, today
from app.config import Settings
from app.domain.directory import Directory, NotFoundError
from app.domain.vacations import VacationLedger
from app.llm.base import ChatModel
from app.llm.costs import LlmSession, PriceTable, Route, choose_model
from app.llm.fake import FakeModel
from app.llm.gateway import GatewayModel
from app.observability.logs import JsonLogger, channel_var, client_var, request_id_var
from app.observability.metrics import Metrics
from app.observability.tracing import Tracer
from app.security import guards

PROTECTED_ANSWER = (
    "Por protección de datos personales no comparto CURP, RFC, NSS, salario, "
    "domicilio ni datos de contacto. Esa información se solicita a RH por el canal "
    "autorizado."
)


class AnswerCache:
    """Caché de respuestas en memoria con caducidad (palanca de costo).

    :param ttl_seconds: Vida de cada respuesta; 0 la apaga
    :type ttl_seconds: int
    :param clock: Reloj inyectado
    :type clock: Clock
    :param max_items: Entradas máximas (se descarta la más vieja)
    :type max_items: int
    """

    def __init__(self, ttl_seconds: int, clock: Clock, max_items: int = 512) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._max = max_items
        self._items: OrderedDict[str, tuple[float, dict]] = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def key(*parts) -> str:
        """Llave estable a partir de las partes de la pregunta.

        :return: Hash SHA-256
        :rtype: str
        """
        raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, key: str) -> dict | None:
        """Respuesta guardada, si sigue vigente.

        :param key: Llave
        :type key: str
        :return: Respuesta o ``None``
        :rtype: dict | None
        """
        if self._ttl <= 0:
            return None
        now = self._clock.now().timestamp()
        with self._lock:
            item = self._items.get(key)
            if item is None or now - item[0] > self._ttl:
                self._items.pop(key, None)
                return None
            return dict(item[1])

    def put(self, key: str, value: dict) -> None:
        """Guarda una respuesta.

        :param key: Llave
        :type key: str
        :param value: Respuesta
        :type value: dict
        """
        if self._ttl <= 0:
            return
        with self._lock:
            self._items[key] = (self._clock.now().timestamp(), dict(value))
            self._items.move_to_end(key)
            while len(self._items) > self._max:
                self._items.popitem(last=False)


@dataclass
class Services:  # pylint: disable=too-many-instance-attributes
    """Dependencias armadas del producto (para inyectarlas en pruebas)."""

    settings: Settings
    clock: Clock
    model: ChatModel
    logger: JsonLogger
    metrics: Metrics
    tracer: Tracer
    directory: Directory
    ledger: VacationLedger
    prices: PriceTable


def build_services(
    settings: Settings,
    clock: Clock,
    logger: JsonLogger,
    model: ChatModel | None = None,
    tracer: Tracer | None = None,
) -> Services:
    """Arma las dependencias a partir de la configuración.

    :param settings: Configuración validada
    :type settings: Settings
    :param clock: Reloj
    :type clock: Clock
    :param logger: Log estructurado
    :type logger: JsonLogger
    :param model: Modelo a usar; por omisión según ``MODEL_PROVIDER``
    :type model: ChatModel | None
    :param tracer: Trazas; por omisión según la configuración
    :type tracer: Tracer | None
    :return: Dependencias
    :rtype: Services
    """
    # pylint: disable=too-many-arguments,too-many-positional-arguments
    directory = Directory.from_file(settings.employees_path)
    if model is None:
        model = (
            GatewayModel(settings)
            if settings.model_provider == "gateway"
            else FakeModel(directory)
        )
    return Services(
        settings=settings,
        clock=clock,
        model=model,
        logger=logger,
        metrics=Metrics(settings.slo_p95_ms),
        tracer=tracer or Tracer(settings),
        directory=directory,
        ledger=VacationLedger.from_file(settings.vacations_path),
        prices=PriceTable.from_file(settings.prices_path),
    )


class HrService:  # pylint: disable=too-many-instance-attributes
    """Casos de uso del HR Assistant.

    :param services: Dependencias armadas
    :type services: Services
    """

    def __init__(self, services: Services) -> None:
        self.s = services
        cfg = services.settings
        self.vacation_agent = VacationAgent(
            services.directory, services.ledger, cfg.subagent_max_steps
        )
        self.summary_agent = SummaryAgent(services.directory, cfg.reflection_max_rounds)
        self.hr_agent = HrAgent(
            services.directory, self.vacation_agent, self.summary_agent
        )
        self.cache = AnswerCache(cfg.answer_cache_ttl_seconds, services.clock)

    def _session(self, route: Route) -> LlmSession:
        return LlmSession(
            self.s.model,
            self.s.prices,
            route,
            self.s.settings.model_max_tokens,
            self.s.clock,
        )

    def _context(self, llm: LlmSession) -> RunContext:
        return RunContext(
            llm=llm,
            logger=self.s.logger,
            as_of=today(self.s.clock),
            request_id=request_id_var.get(),
            compact=self.s.settings.compact_prompts,
        )

    def _metadata(self, name: str) -> dict:
        return {
            "request_id": request_id_var.get(),
            "client": client_var.get(),
            "channel": channel_var.get(),
            "use_case": name,
            "environment": self.s.settings.environment,
        }

    def _finish(self, llm: LlmSession, started: float, extra: dict) -> dict:
        """Cierra la corrida: métricas, log ``agent_run`` y números de costo."""
        usage = llm.usage
        latency = round((self.s.clock.monotonic() - started) * 1000, 2)
        numbers = {
            "model": usage.models[0] if usage.models else "none",
            "models": list(usage.models),
            "route": llm.route.reason,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "model_calls": usage.model_calls,
            "cached_calls": usage.cached_calls,
            "cost_usd": round(usage.cost_usd, 8),
            "latency_ms": latency,
        }
        self.s.metrics.record_agent({**numbers, **extra})
        self.s.logger.event("agent_run", **numbers, **extra)
        return numbers

    async def ask(  # pylint: disable=too-many-locals
        self, question: str, history: list[dict]
    ) -> dict:
        """Responde una pregunta libre con el agente supervisor.

        :param question: Pregunta original
        :type question: str
        :param history: Historial que manda el cliente
        :type history: list[dict]
        :return: Respuesta con pasos, herramientas, costo y detalles
        :rtype: dict
        :raises guards.GuardRejection: Si la política rechaza la pregunta
        :raises app.llm.base.ModelUnavailable: Si el modelo no responde
        """
        cfg = self.s.settings
        checked = self._check(question)
        window = history[-cfg.history_window :] if cfg.history_window else []
        window = [
            {"role": m["role"], "content": guards.pii.mask(m["content"])}
            for m in window
        ]
        route = choose_model(
            checked.text,
            cfg.model_small,
            cfg.model_large,
            cfg.routing,
            cfg.router_max_chars,
        )
        key = AnswerCache.key(
            checked.text, window, today(self.s.clock).isoformat(), route.model
        )
        cached = self.cache.get(key)
        if cached is not None:
            self.s.metrics.answer_cache_hits += 1
            self.s.logger.event("answer_cache_hit", route=route.reason)
            return {
                **cached,
                "cost_usd": 0.0,
                "input_tokens": 0,
                "output_tokens": 0,
                "model_calls": 0,
                "answer_cache": True,
            }
        started = self.s.clock.monotonic()
        llm = self._session(route)
        if checked.asks_protected_data:
            self.s.logger.audit("protected_data_request")
            result = {
                "answer": PROTECTED_ANSWER,
                "steps": 0,
                "tools_used": [],
                "thoughts": [],
                "stopped": False,
                "parse_errors": 0,
            }
            ctx = self._context(llm)
        else:
            ctx = self._context(llm)
            with self.s.tracer.scope("ask", self._metadata("ask")):
                result = await self.hr_agent.run(
                    checked.text, window, ctx, cfg.agent_max_steps
                )
        output = guards.check_output(result["answer"])
        self._audit_output(output)
        intent = self._intent(result["tools_used"], checked.asks_protected_data)
        numbers = self._finish(
            llm,
            started,
            {
                "intent": intent,
                "steps": result["steps"],
                "tools": result["tools_used"],
                "stopped": result["stopped"],
                "question_chars": len(question),
                "history_messages": len(window),
                "parse_errors": result["parse_errors"],
                "pii_in_question": list(checked.pii_kinds),
            },
        )
        body = {
            "answer": output.text,
            "steps": result["steps"],
            "tools_used": result["tools_used"],
            "reasoning": result["thoughts"],
            "intent": intent,
            "pii_detected": list(checked.pii_kinds),
            "details": ctx.details,
            "answer_cache": False,
            **numbers,
        }
        self.cache.put(key, body)
        return body

    def _check(self, question: str) -> guards.CheckedInput:
        try:
            checked = guards.check_input(question, self.s.settings.pii_policy)
        except guards.GuardRejection as exc:
            self.s.logger.audit("input_rejected", reason=exc.reason)
            self.s.metrics.increment(f"guard_{exc.reason}")
            raise
        if checked.pii_kinds:
            self.s.logger.audit(
                "pii_detected", where="input", kinds=list(checked.pii_kinds)
            )
            self.s.metrics.increment("pii_masked_input")
        return checked

    def _audit_output(self, output: guards.CheckedOutput) -> None:
        if output.pii_kinds:
            self.s.logger.audit(
                "pii_detected", where="output", kinds=list(output.pii_kinds)
            )
            self.s.metrics.increment("pii_masked_output")
        if output.leaked_prompt:
            self.s.logger.audit("output_blocked", reason="system_prompt_leak")
            self.s.metrics.increment("guard_prompt_leak")

    @staticmethod
    def _intent(tools: list[str], protected: bool) -> str:
        if protected:
            return "protected_data"
        for tool, intent in (
            ("vacation_balance", "vacation"),
            ("department_summary", "department_summary"),
            ("get_employee", "employee"),
            ("search_by_department", "department"),
        ):
            if tool in tools:
                return intent
        return "other"

    async def vacation(self, employee_id: str, question: str = "") -> dict:
        """Saldo de vacaciones con el agente ReAct (lo usa la herramienta MCP).

        :param employee_id: Id con forma ``EMP-0000``
        :type employee_id: str
        :param question: Contexto libre opcional (se revisa y enmascara)
        :type question: str
        :return: Reporte del subagente más costo y latencia
        :rtype: dict
        """
        cfg = self.s.settings
        text = self._check(question).text if question.strip() else "saldo de vacaciones"
        llm = self._session(Route(cfg.model_small, "specialist:vacation"))
        started = self.s.clock.monotonic()
        ctx = self._context(llm)
        with self.s.tracer.scope(
            "vacation_balance", self._metadata("vacation_balance")
        ):
            report = await self.vacation_agent.run(employee_id, text, ctx)
        report["answer"] = guards.check_output(report["answer"]).text
        numbers = self._finish(
            llm,
            started,
            {
                "intent": "vacation",
                "steps": report["steps"],
                "tools": report["tools_used"],
                "stopped": report["stopped"],
            },
        )
        return {**report, **numbers}

    async def summary(self, department: str) -> dict:
        """Resumen de un área con el agente de reflexión (herramienta MCP).

        :param department: Nombre del departamento (sin importar acentos)
        :type department: str
        :return: Reporte del subagente más costo y latencia
        :rtype: dict
        :raises NotFoundError: Si el departamento no existe
        """
        cfg = self.s.settings
        name = self.s.directory.resolve_department(department)
        if name is None:
            known = ", ".join(self.s.directory.departments())
            raise NotFoundError(
                f"No existe el departamento '{department}'. Existen: {known}."
            )
        llm = self._session(Route(cfg.model_small, "specialist:summary"))
        started = self.s.clock.monotonic()
        ctx = self._context(llm)
        with self.s.tracer.scope(
            "department_summary", self._metadata("department_summary")
        ):
            report = await self.summary_agent.run(name, ctx)
        report["answer"] = guards.check_output(report["answer"]).text
        numbers = self._finish(
            llm,
            started,
            {
                "intent": "department_summary",
                "steps": report["reflection_rounds"] + 1,
                "tools": ["department_facts"],
                "stopped": report["fallback"],
            },
        )
        return {**report, **numbers}
