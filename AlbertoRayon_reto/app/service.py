"""El servicio que une todo: guardas, enrutamiento, caché, agentes y métricas.

La API HTTP y el servidor MCP usan esta misma clase, así que los dos canales
tienen las mismas protecciones y las mismas mediciones.
"""

import hashlib
import json
import re
import threading

from app import guards, tracing
from app.agents.base import AgentResult, Tool
from app.agents.react import ReactAgent
from app.agents.summary import SummaryAgent
from app.agents.supervisor import Supervisor
from app.clock import SystemClock
from app.config import Settings
from app.directory import Directory
from app.llm import FakeModel, GatewayModel, ModelCaller, Prices, Usage, choose_model
from app.logs import JsonLogger, request_id_var, trace_metadata
from app.metrics import Metrics
from app.vacations import VacationLedger

EMPLOYEE_ID = re.compile(r"^EMP-\d{4}$")
DIRECTORY_ROLE = (
    "Eres el HR Assistant: respondes preguntas sobre empleados con el directorio."
)
VACATION_ROLE = (
    "Eres el agente de vacaciones del HR Assistant: consultas el saldo de "
    "vacaciones según la Ley Federal del Trabajo."
)
MAX_CACHE_ENTRIES = 500


class ResponseCache:
    """Caché de respuestas en memoria, con vencimiento; apagada si el TTL es 0."""

    def __init__(self, ttl_seconds: int, clock):
        self._ttl = ttl_seconds
        self._clock = clock
        self._entries: dict[str, tuple[float, dict]] = {}
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        """Indica si la caché está encendida."""
        return self._ttl > 0

    @staticmethod
    def key(model: str, question: str, history: list[dict]) -> str:
        """Llave de una pregunta: modelo, pregunta e historial que viaja.

        :param model: Modelo elegido
        :type model: str
        :param question: Pregunta enmascarada
        :type question: str
        :param history: Historial dentro de la ventana
        :type history: list[dict]
        :return: Hash SHA-256; el texto nunca se guarda como llave
        :rtype: str
        """
        raw = json.dumps([model, question.strip().lower(), history], sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, key: str) -> dict | None:
        """Devuelve la respuesta guardada, si no ha vencido.

        :param key: Llave de :meth:`key`
        :type key: str
        :return: La respuesta, o ``None``
        :rtype: dict | None
        """
        now = self._clock.now().timestamp()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or now - entry[0] >= self._ttl:
                self._entries.pop(key, None)
                return None
            return dict(entry[1])

    def put(self, key: str, value: dict) -> None:
        """Guarda una respuesta.

        :param key: Llave de :meth:`key`
        :type key: str
        :param value: Respuesta a guardar
        :type value: dict
        """
        with self._lock:
            if len(self._entries) >= MAX_CACHE_ENTRIES:
                self._entries.pop(next(iter(self._entries)))
            self._entries[key] = (self._clock.now().timestamp(), dict(value))


class HRService:  # pylint: disable=too-many-instance-attributes
    """Punto de entrada único a los agentes."""

    def __init__(self, settings: Settings, model=None, clock=None, logger=None):
        self.settings = settings
        self.clock = clock or SystemClock()
        self.logger = logger or JsonLogger(settings.service_name, self.clock)
        self.metrics = Metrics(settings.slo_p95_ms)
        self.tracing_enabled = tracing.configure(settings)
        self.directory = Directory.from_file(settings.employees_path)
        self._ledger = VacationLedger.from_file(settings.vacations_path)
        self._prices = Prices.from_file(settings.prices_path)
        self._cache = ResponseCache(settings.response_cache_ttl_seconds, self.clock)
        if model is None:
            model = (
                FakeModel(self.directory.departments())
                if settings.model_provider == "fake"
                else GatewayModel(settings)
            )
        caller = ModelCaller(model, self._prices)
        employee_tool = Tool(
            "get_employee", "ficha de un empleado por id (employee_id)",
            self._get_employee,
        )
        self._directory_agent = ReactAgent(
            "directory_agent", DIRECTORY_ROLE,
            [employee_tool,
             Tool("search_by_department",
                  "empleados de un departamento (department)",
                  self._search_by_department)],
            caller, settings, self.logger,
        )
        self._vacation_agent = ReactAgent(
            "vacation_agent", VACATION_ROLE,
            [Tool("get_vacation_balance",
                  "saldo de vacaciones verificado de un empleado (employee_id)",
                  self._get_vacation_balance, return_direct=True),
             employee_tool],
            caller, settings, self.logger,
        )
        self._summary_agent = SummaryAgent(
            self.directory, caller, self.clock, self.logger
        )
        self._supervisor = Supervisor(
            self.directory, self._directory_agent, self._vacation_agent,
            self._summary_agent, self.logger,
        )

    # --- herramientas de solo lectura -------------------------------------------

    def _get_employee(self, employee_id: str) -> str:
        return self.directory.get(employee_id).describe()

    def _search_by_department(self, department: str) -> str:
        people = self.directory.by_department(department)
        return "; ".join(person.describe() for person in people)

    def _balance(self, employee_id: str):
        employee = self.directory.get(employee_id)
        return self._ledger.balance(employee, self.clock.now().date())

    def _get_vacation_balance(self, employee_id: str) -> str:
        return self._balance(employee_id).describe()

    # --- flujo común ------------------------------------------------------------

    def _guard(self, question: str, history: list[dict]):
        try:
            guarded = guards.check_input(question)
            clean_history = []
            pii_types = list(guarded.pii_types)
            for message in history:
                checked = guards.check_input(message["content"])
                pii_types += [t for t in checked.pii_types if t not in pii_types]
                clean_history.append({"role": message["role"], "content": checked.text})
        except guards.GuardBlocked as blocked:
            self.metrics.count("guard_blocked")
            self.logger.audit("guard_blocked", reason=blocked.reason)
            raise
        if pii_types:
            self.logger.audit("pii_masked", where="input", types=pii_types)
        window = self.settings.history_window
        return guarded.text, clean_history[-window:] if window else [], pii_types

    def _finish(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self, result: AgentResult, route: str, pii_types: list[str],
        sizes: tuple[int, int], cache: str = "off",
    ) -> dict:
        checked = guards.check_output(result.answer, self.settings.max_answer_chars)
        if checked.flags:
            self.metrics.count("output_guard_flag")
            self.logger.audit("output_guard", flags=checked.flags,
                              types=checked.pii_types)
        usage = result.usage
        response = {
            "answer": checked.text,
            "steps": usage.steps,
            "tools_used": result.tools_used,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "request_id": request_id_var.get(),
            "model": result.model,
            "route": route,
            "cached_calls": usage.cached_calls,
            "cost_usd": round(usage.cost_usd, 10),
            "agent": result.agent,
            "reasoning": result.reasoning,
            "pii_masked": pii_types,
            "cache": cache,
        }
        baseline = self._prices.cost(
            self.settings.model_large, usage.input_tokens, usage.output_tokens
        )
        self.metrics.record_run(response, baseline)
        self.logger.event(
            "agent_run", agent=result.agent, question_chars=sizes[0],
            history_messages=sizes[1], steps=usage.steps, tools=result.tools_used,
            input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
            stopped=result.stopped, model=result.model, route=route,
            cost_usd=response["cost_usd"], cached_calls=usage.cached_calls,
            cache=cache, pii_types=pii_types,
        )
        return response

    # --- operaciones públicas ---------------------------------------------------

    def ask(self, question: str, history: list[dict] | None = None) -> dict:
        """Responde una pregunta con el supervisor y sus especialistas.

        :param question: Pregunta de la persona
        :type question: str
        :param history: Mensajes anteriores ``{"role", "content"}``
        :type history: list[dict] | None
        :return: Respuesta con pasos, herramientas, tokens, modelo y costo
        :rtype: dict
        :raises app.guards.GuardBlocked: Si la guarda de entrada la bloquea
        :raises app.llm.ModelUnavailable: Si el modelo real no responde
        """
        history = history or []
        masked, window, pii_types = self._guard(question, history)
        model, route = choose_model(question, self.settings)
        sizes = (len(question), len(history))
        key = ResponseCache.key(model, masked, window)
        if self._cache.enabled:
            hit = self._cache.get(key)
            if hit is not None:
                result = AgentResult(
                    hit["agent"], hit["answer"], model, Usage(), hit["tools_used"],
                    hit["reasoning"],
                )
                return self._finish(result, route, pii_types, sizes, "hit")
        result = self._supervisor.run(masked, window, model, trace_metadata())
        if self._cache.enabled and not result.stopped:
            self._cache.put(key, {
                "agent": result.agent, "answer": result.answer,
                "tools_used": result.tools_used, "reasoning": result.reasoning,
            })
        cache = "miss" if self._cache.enabled else "off"
        return self._finish(result, route, pii_types, sizes, cache)

    def vacation_balance(self, employee_id: str) -> dict:
        """Saldo de vacaciones de un empleado, con el agente ReAct de vacaciones.

        El agente razona y elige la herramienta; las cifras salen del cálculo en
        código. Si la respuesta del modelo no es ese cálculo, se entrega el valor
        verificado y el razonamiento lo dice.

        :param employee_id: Id con la forma ``EMP-0001``
        :type employee_id: str
        :return: La respuesta de :meth:`ask` más ``balance`` con las cifras
        :rtype: dict
        :raises ValueError: Si el id no tiene la forma esperada
        :raises app.directory.NotFoundError: Si el empleado no existe
        """
        employee_id = str(employee_id).strip().upper()
        if not EMPLOYEE_ID.match(employee_id):
            raise ValueError("employee_id debe tener la forma EMP-0001")
        balance = self._balance(employee_id)
        question = f"¿Cuál es el saldo de vacaciones de {employee_id}?"
        model, route = choose_model(question, self.settings)
        result = self._vacation_agent.run(question, [], model)
        if result.answer != balance.describe():
            self.logger.audit("verified_override", agent=result.agent)
            result.reasoning.append(
                "La respuesta del modelo no coincidía con el cálculo: se entrega el "
                "valor verificado."
            )
            result.answer = balance.describe()
        response = self._finish(result, route, [], (len(question), 0))
        response["balance"] = balance.as_dict()
        return response

    def department_summary(self, department: str) -> dict:
        """Resumen de un departamento, con el agente de reflexión.

        :param department: Nombre del departamento
        :type department: str
        :return: La respuesta de :meth:`ask`, con la crítica en ``reasoning``
        :rtype: dict
        :raises app.directory.NotFoundError: Si el departamento no existe
        """
        department = guards.check_input(str(department)).text
        question = f"Resume el departamento de {department}"
        model, route = choose_model(question, self.settings)
        result = self._summary_agent.run(department, model)
        return self._finish(result, route, [], (len(question), 0))

    def graphs(self) -> dict:
        """Diagramas Mermaid de los grafos, para la documentación.

        :return: Un diagrama por grafo
        :rtype: dict
        """
        return {
            "supervisor": self._supervisor.mermaid(),
            "react": self._directory_agent.mermaid(),
            "reflection": self._summary_agent.mermaid(),
        }
