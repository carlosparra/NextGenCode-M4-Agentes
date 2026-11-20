"""Orquestador de los agentes de cada ``POST /ask`` (spec 06).

``RequestPipeline.run`` encadena, en este orden:

1. ``guard``: inyeccion y PII de la entrada (spec 05).
2. ``supervisor``: reglas y, si no alcanzan, una llamada a
   ``MODEL_SMALL``.
3. El enrutador de costo de la sesion 3 (``route_question`` y
   ``window_history``), que elige el modelo **del especialista**.
4. Un solo especialista: ``directory`` o ``policy``. Con
   ``rule:policy``, ``search_policy`` corre en codigo antes de la
   pregunta; con ``rule:policy_employee`` (Adenda 1), tambien
   ``vacation_days`` del empleado, con el reloj inyectado.
5. ``reviewer``: validacion de salida, comprobacion contra los datos y
   recorte.

Cada etapa es una funcion **sin parametros** que lee y escribe un
``RequestContext`` local de la peticion y devuelve un resumen sin texto
(tipos, conteos y decisiones). Todas pasan por ``_stage``, el unico
punto donde se envuelven para la traza raiz.

Traza (spec 06, punto 6): cada peticion abre un solo run raiz
``request`` (``chain``) y, dentro, ``agent.guard``,
``agent.supervisor``, ``agent.directory`` o ``agent.policy`` y
``agent.reviewer``. Los spans ``security`` quedan dentro del agente que
los registra porque el anidamiento sigue el contexto de ejecucion.
Todos los runs llevan ``request_id`` y ``client``; el raiz y el
especialista, ademas, ``specialist`` y ``supervisor_route``.

:seealso: ``spec/06-multiagente.md`` y ``output/plan.md``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast

from app.agent import Agent, Seed, directory_tools, policy_tools
from app.clock import Clock, SystemClock
from app.completion import Model
from app.config import Settings
from app.directory import Directory
from app.guard import GuardResult, screen_input
from app.guardrails import TOOL_SEARCH_POLICY, TOOL_VACATION_DAYS
from app.logs import JsonLogger, NullLogger
from app.policies import PolicyBook
from app.pricing import PriceTable
from app.prompts import POLICY_PROMPT
from app.reviewer import Review, Reviewer, ReviewInput
from app.routing import route_question, window_history
from app.security import Audit
from app.supervisor import (
    ROUTE_POLICY,
    ROUTE_POLICY_EMPLOYEE,
    SPECIALIST_DIRECTORY,
    SPECIALIST_POLICY,
    VACATION_TOPIC,
    Decision,
    Supervisor,
)
from app.tracing import Tracer
from app.vacations import VacationBook

AGENT_GUARD = "guard"
AGENT_SUPERVISOR = "supervisor"
AGENT_REVIEWER = "reviewer"
# Spec 06, punto 6: run raiz por peticion y un run hijo por agente.
ROOT_RUN = "request"
AGENT_RUN_PREFIX = "agent."
CHAIN = "chain"


@dataclass
class RequestContext:  # pylint: disable=too-many-instance-attributes
    """Estado local de una peticion; nunca se comparte entre peticiones.

    :param question: Pregunta validada (antes de ``guard``).
    :type question: str
    :param history: Historial recibido.
    :type history: list[dict[str, str]]
    :param request_id: Id de la peticion.
    :type request_id: str
    :param client: Cliente autenticado (nunca su clave).
    :type client: str
    """

    question: str
    history: list[dict[str, str]]
    request_id: str
    client: str
    guard: GuardResult | None = None
    decision: Decision | None = None
    result: dict[str, Any] = field(default_factory=dict)
    review: Review | None = None
    agents: list[str] = field(default_factory=list)

    def metadata(self) -> dict[str, str]:
        """Metadatos comunes de la peticion para trazas.

        :return: ``request_id`` y ``client``.
        :rtype: dict[str, str]
        """
        return {"request_id": self.request_id, "client": self.client}


class RequestPipeline:  # pylint: disable=too-many-instance-attributes
    """Corre guard, supervisor, un especialista y reviewer.

    :param settings: Configuracion de la aplicacion.
    :type settings: app.config.Settings
    :param models: Modelos por nombre.
    :type models: dict[str, app.completion.Model]
    :param directory: Directorio de empleados.
    :type directory: app.directory.Directory
    :param policies: Libro de politicas.
    :type policies: app.policies.PolicyBook
    :param prices: Tabla de precios.
    :type prices: app.pricing.PriceTable
    :param logger: Logger de eventos JSON.
    :type logger: app.logs.JsonLogger
    :param tracer: Trazador.
    :type tracer: app.tracing.Tracer
    :param audit: Auditoria de seguridad.
    :type audit: app.security.Audit
    """

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        settings: Settings,
        models: dict[str, Model],
        directory: Directory,
        policies: PolicyBook,
        prices: PriceTable,
        logger: JsonLogger | NullLogger,
        tracer: Tracer,
        audit: Audit,
        clock: Clock | None = None,
    ) -> None:
        """Construye los agentes con sus dependencias.

        :param settings: Configuracion de la aplicacion.
        :type settings: app.config.Settings
        :param models: Modelos por nombre.
        :type models: dict[str, app.completion.Model]
        :param directory: Directorio de empleados.
        :type directory: app.directory.Directory
        :param policies: Libro de politicas.
        :type policies: app.policies.PolicyBook
        :param prices: Tabla de precios.
        :type prices: app.pricing.PriceTable
        :param logger: Logger de eventos JSON.
        :type logger: app.logs.JsonLogger
        :param tracer: Trazador.
        :type tracer: app.tracing.Tracer
        :param audit: Auditoria de seguridad.
        :type audit: app.security.Audit
        :param clock: Reloj inyectado para ``vacation_days`` (Adenda 1);
            por omision el del sistema.
        :type clock: app.clock.Clock | None
        """
        self._settings = settings
        self._models = models
        self._tracer = tracer
        self._audit = audit
        self._supervisor = Supervisor(directory.departments, policies, tracer)
        common = {
            "directory": directory,
            "prices": prices,
            "max_steps": settings.agent_max_steps,
            "logger": logger,
            "tracer": tracer,
            "audit": audit,
        }
        # Minimo privilegio: cada especialista tiene su propio registro.
        self._specialists = {
            SPECIALIST_DIRECTORY: Agent(
                **common,
                name=SPECIALIST_DIRECTORY,
                tools=directory_tools(directory),
            ),
            SPECIALIST_POLICY: Agent(
                **common,
                name=SPECIALIST_POLICY,
                tools=policy_tools(
                    policies,
                    VacationBook(directory, clock or SystemClock()),
                ),
                system_prompt=POLICY_PROMPT,
            ),
        }
        self._reviewer = Reviewer(
            directory.ids,
            audit,
            settings.secret_values(),
            settings.max_answer_chars,
        )

    @property
    def audit(self) -> Audit:
        """Auditoria compartida por todos los agentes.

        :return: Auditoria de seguridad.
        :rtype: app.security.Audit
        """
        return self._audit

    def specialist(self, name: str) -> Agent:
        """Devuelve un especialista por nombre.

        :param name: ``directory`` o ``policy``.
        :type name: str
        :return: El especialista.
        :rtype: app.agent.Agent
        """
        return self._specialists[name]

    def run(
        self,
        question: str,
        history: list[dict[str, str]],
        request_id: str,
        client: str,
    ) -> dict[str, Any]:
        """Corre los agentes de una peticion.

        :param question: Pregunta ya validada (422 se decide antes).
        :type question: str
        :param history: Historial recibido.
        :type history: list[dict[str, str]]
        :param request_id: Id de la peticion.
        :type request_id: str
        :param client: Cliente autenticado.
        :type client: str
        :return: Resultado del especialista con la respuesta revisada,
            ``redactions``, ``specialist``, ``agents`` y
            ``supervisor_route``.
        :rtype: dict[str, Any]
        :raises app.completion.ModelUnavailable: Si un modelo falla.
        """
        ctx = RequestContext(question, list(history), request_id, client)
        # Un solo run raiz por peticion; la funcion trazada no recibe texto.
        traced = self._tracer.traceable(ROOT_RUN, CHAIN, ctx.metadata())(
            lambda: self._request(ctx)
        )
        traced()
        return self._response(ctx)

    # -- Etapas ---------------------------------------------------------

    def _request(self, ctx: RequestContext) -> dict[str, Any]:
        """Cuerpo del run raiz ``request``: corre los agentes en orden.

        Despues del supervisor agrega ``specialist`` y
        ``supervisor_route`` a los metadatos del raiz con
        ``Tracer.annotate``.

        :param ctx: Contexto de la peticion.
        :type ctx: RequestContext
        :return: Resumen sin texto: especialista, motivo y agentes.
        :rtype: dict[str, Any]
        """
        self._stage(AGENT_GUARD, lambda: self._guard(ctx), ctx)
        self._stage(AGENT_SUPERVISOR, lambda: self._decide(ctx), ctx)
        decision = cast(Decision, ctx.decision)
        routing = {
            "specialist": decision.specialist,
            "supervisor_route": decision.route,
        }
        self._tracer.annotate(routing)
        self._stage(
            decision.specialist, lambda: self._specialist(ctx), ctx, routing
        )
        self._stage(AGENT_REVIEWER, lambda: self._review(ctx), ctx)
        return {**routing, "agents": list(ctx.agents)}

    def _stage(
        self,
        name: str,
        func: Callable[[], dict[str, Any]],
        ctx: RequestContext,
        extra: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Corre una etapa como run hijo ``agent.<nombre>`` del raiz.

        Anota el agente en ``ctx.agents``. La funcion trazada no tiene
        parametros: el texto vive en ``ctx`` y no llega a la traza.

        :param name: Nombre del agente (``guard``, ``supervisor``,
            ``directory``, ``policy`` o ``reviewer``).
        :type name: str
        :param func: Etapa sin parametros; devuelve un resumen sin texto.
        :type func: collections.abc.Callable[[], dict[str, Any]]
        :param ctx: Contexto de la peticion.
        :type ctx: RequestContext
        :param extra: Metadatos adicionales del run, por ejemplo
            ``specialist`` y ``supervisor_route`` del especialista.
        :type extra: dict[str, str] | None
        :return: Resumen de la etapa.
        :rtype: dict[str, Any]
        """
        ctx.agents.append(name)
        metadata = {**ctx.metadata(), **(extra or {})}
        traced = self._tracer.traceable(AGENT_RUN_PREFIX + name, CHAIN, metadata)(
            func
        )
        return traced()

    def _guard(self, ctx: RequestContext) -> dict[str, Any]:
        """Etapa ``guard``: limpia la entrada.

        :param ctx: Contexto de la peticion.
        :type ctx: RequestContext
        :return: ``{"pii_kinds": [...], "injection": bool}``.
        :rtype: dict[str, Any]
        """
        ctx.guard = screen_input(
            ctx.question, ctx.history, self._audit, (ctx.request_id, ctx.client)
        )
        # Desde aqui solo existe el texto limpio.
        ctx.question, ctx.history = ctx.guard.question, ctx.guard.history
        return ctx.guard.summary()

    def _decide(self, ctx: RequestContext) -> dict[str, Any]:
        """Etapa ``supervisor``: elige el especialista.

        :param ctx: Contexto de la peticion.
        :type ctx: RequestContext
        :return: ``{"specialist": ..., "route": ...}``.
        :rtype: dict[str, Any]
        """
        small = self._models[self._settings.model_small]
        ctx.decision = self._supervisor.decide(ctx.question, small, ctx.metadata())
        return ctx.decision.summary()

    def _specialist(self, ctx: RequestContext) -> dict[str, Any]:
        """Etapa del especialista elegido, con su modelo y su bucle.

        :param ctx: Contexto de la peticion.
        :type ctx: RequestContext
        :return: Pasos, herramientas y motivo de parada, sin texto.
        :rtype: dict[str, Any]
        """
        decision = cast(Decision, ctx.decision)
        route = route_question(ctx.question, self._settings)
        prefetch = self._prefetch(decision)
        seed = None
        if decision.completion is not None:
            seed = Seed(decision.completion, self._settings.model_small)
        ctx.result = self._specialists[decision.specialist].run(
            ctx.question,
            window_history(ctx.history, self._settings.history_window),
            model=self._models[route.model],
            request_id=ctx.request_id,
            route=route.reason,
            client=ctx.client,
            supervisor_route=decision.route,
            prefetch=prefetch,
            seed=seed,
        )
        return {
            "specialist": decision.specialist,
            "steps": ctx.result["steps"],
            "tools": list(ctx.result["tools_used"]),
            "stopped": ctx.result["stopped"],
        }

    @staticmethod
    def _prefetch(decision: Decision) -> list[tuple[str, dict[str, Any]]]:
        """Consultas que corren en codigo antes de llamar al modelo.

        - ``rule:policy``: ``search_policy`` con el tema encontrado.
        - ``rule:policy_employee`` (Adenda 1): ``search_policy`` del tema
          ``vacaciones`` y ``vacation_days`` del primer id, en ese orden.

        :param decision: Decision del supervisor.
        :type decision: app.supervisor.Decision
        :return: Pares ``(herramienta, args)``; vacia si no aplica.
        :rtype: list[tuple[str, dict[str, Any]]]
        """
        if decision.route == ROUTE_POLICY and decision.topic:
            # La politica se consulta en codigo: el modelo siempre la tiene.
            return [(TOOL_SEARCH_POLICY, {"topic": decision.topic})]
        if decision.route == ROUTE_POLICY_EMPLOYEE and decision.employee_id:
            return [
                (TOOL_SEARCH_POLICY, {"topic": decision.topic or VACATION_TOPIC}),
                (TOOL_VACATION_DAYS, {"employee_id": decision.employee_id}),
            ]
        return []

    def _review(self, ctx: RequestContext) -> dict[str, Any]:
        """Etapa ``reviewer``: valida y comprueba la respuesta.

        :param ctx: Contexto de la peticion.
        :type ctx: RequestContext
        :return: ``{"controls": [...], "replaced": bool}``.
        :rtype: dict[str, Any]
        """
        ctx.review = self._reviewer.review(
            ReviewInput(
                answer=ctx.result["answer"],
                question=ctx.question,
                specialist=ctx.result["specialist"],
                policy_texts=list(ctx.result.get("policy_texts", [])),
                vacation_results=list(ctx.result.get("vacation_results", [])),
                request_id=ctx.request_id,
                client=ctx.client,
            )
        )
        return ctx.review.summary()

    @staticmethod
    def _response(ctx: RequestContext) -> dict[str, Any]:
        """Arma el resultado final de la peticion.

        :param ctx: Contexto de la peticion ya revisada.
        :type ctx: RequestContext
        :return: Resultado con la respuesta revisada y los campos nuevos.
        :rtype: dict[str, Any]
        """
        review = cast(Review, ctx.review)
        guard = cast(GuardResult, ctx.guard)
        result = dict(ctx.result)
        result["answer"] = review.text
        result["input_redactions"] = list(guard.kinds)
        result["output_redactions"] = list(review.kinds)
        result["agents"] = list(ctx.agents)
        return result
