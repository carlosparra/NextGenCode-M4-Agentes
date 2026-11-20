"""Agente del HR Assistant (especialista con bucle acotado).

Ejecuta el bucle agente: envia mensajes al modelo, interpreta
la respuesta JSON, invoca herramientas y acumula pasos hasta
obtener una respuesta o alcanzar el tope.

Por cada herramienta emite un evento ``audit`` y al terminar un
``agent_run`` con conteos, modelo, ruta y costo; nunca registra el
texto de la pregunta ni de la respuesta. La corrida, cada llamada al
modelo y cada herramienta se trazan con el ``app.tracing.Tracer``
inyectado.

Desde la sesion 3 el modelo se elige por peticion (``run`` lo recibe)
y el costo de cada llamada se suma con la tabla de precios; una
llamada que vino de la cache del gateway cuenta en ``cached_calls`` y
no cuesta.

Desde la sesion 4 ``run`` recibe el ``client`` que hizo la pregunta y
lo pone en cada ``audit``, en ``agent_run`` y en los metadatos de las
trazas. La clave del cliente nunca llega al agente.

Desde el reto de seguridad reforzada:

- Antes de ejecutar una herramienta, ``validate_tool_args`` revisa sus
  argumentos (minimo privilegio). Un argumento invalido no llega al
  directorio: el modelo recibe un error legible, sin el valor, y se
  registra ``security`` con ``control=tool_args``.
- Los argumentos del evento ``audit`` pasan por ``redact_pii``.
- El nombre de herramienta que manda el modelo solo se repite en
  ``audit``, ``agent_run``, ``security`` y en el error si es conocido;
  si no, se registra ``unknown_tool`` (``safe_tool_name``).

Desde la spec 06 el agente es un **especialista**:

- Tiene nombre (``directory`` por omision), su propio registro de
  herramientas y un prompt de sistema opcional. ``directory`` solo
  tiene ``get_employee`` y ``search_by_department``; ``policy`` solo
  ``search_policy``. Una herramienta ajena se trata como
  ``unknown_tool`` (minimo privilegio entre especialistas).
- ``run`` acepta ``prefetch`` (una herramienta que el producto ejecuta
  en codigo antes de la pregunta; cuenta en ``tools_used`` y deja su
  ``audit``) y ``seed`` (la llamada del supervisor, que suma tokens y
  costo).
- La validacion de salida ya no vive aqui: la hace ``app.reviewer``.
  La funcion trazada ``agent_run`` devuelve solo un resumen sin texto.

Desde la Adenda 1 de la spec 06, ``policy`` tiene ademas
``vacation_days`` (``directory`` no), ``prefetch`` acepta una lista de
herramientas que corren en orden y los resultados de ``vacation_days``
se guardan en ``vacation_results`` para el revisor. Un ``vacation_days``
con formato invalido no se ejecuta ni deja ``audit``: registra
``tool_args`` y el modelo recibe ``{"error": "empleado no encontrado"}``.

:seealso: ADR 0003 sobre el bucle acotado del agente,
    ``spec/02-observability.md``, ``spec/03-costs.md``,
    ``spec/05-security-hardening.md`` y ``spec/06-multiagente.md``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from app.completion import TOOL_RESULT_PREFIX, Completion, Model
from app.directory import Directory
from app.guardrails import (
    CONTROL_TOOL_ARGS,
    TOOL_GET_EMPLOYEE,
    TOOL_SEARCH_BY_DEPARTMENT,
    TOOL_SEARCH_POLICY,
    TOOL_VACATION_DAYS,
    validate_tool_args,
)
from app.logs import JsonLogger, NullLogger
from app.pii import redact_pii
from app.policies import PolicyBook
from app.pricing import PriceTable
from app.security import STAGE_OUTPUT, Audit, NullAudit
from app.tracing import Tracer, TracingOptions
from app.vacations import EMPLOYEE_NOT_FOUND, VacationBook, is_vacation_result

FALLBACK_MESSAGE = (
    "No pude completar la respuesta. "
    "Intenta con una pregunta más concreta."
)
STOPPED_ANSWER = "answer"
STOPPED_MAX_STEPS = "max_steps"
NO_REQUEST_ID = "-"
NO_ROUTE = "-"
NO_CLIENT = "-"
DEFAULT_AGENT_NAME = "directory"
# Argumentos que se registran en ``audit`` por herramienta conocida.
AUDITED_ARGS = {
    TOOL_GET_EMPLOYEE: ("employee_id",),
    TOOL_SEARCH_BY_DEPARTMENT: ("department",),
    TOOL_SEARCH_POLICY: ("topic",),
    TOOL_VACATION_DAYS: ("employee_id",),
}
MAX_AUDIT_ARG_CHARS = 64
DEFAULT_MAX_ANSWER_CHARS = 2000
KNOWN_TOOLS = (
    TOOL_GET_EMPLOYEE,
    TOOL_SEARCH_BY_DEPARTMENT,
    TOOL_SEARCH_POLICY,
    TOOL_VACATION_DAYS,
)
UNKNOWN_TOOL_KIND = "unknown_tool"
UNKNOWN_TOOL_REASON = "herramienta desconocida"
INVALID_ARGS_TEMPLATE = "argumento inválido para {tool}: {reason}"

ToolFunc = Callable[[Mapping[str, Any]], Any]
Prefetch = tuple[str, dict[str, Any]]


def directory_tools(directory: Directory) -> dict[str, ToolFunc]:
    """Herramientas del especialista ``directory``.

    :param directory: Directorio de empleados.
    :type directory: app.directory.Directory
    :return: ``get_employee`` y ``search_by_department``.
    :rtype: dict[str, collections.abc.Callable]
    """
    return {
        TOOL_GET_EMPLOYEE: lambda args: directory.get_employee(
            str(args.get("employee_id", "")).strip()
        ),
        TOOL_SEARCH_BY_DEPARTMENT: lambda args: directory.search_by_department(
            str(args.get("department", ""))
        ),
    }


def policy_tools(
    policies: PolicyBook, vacations: VacationBook | None = None
) -> dict[str, ToolFunc]:
    """Herramientas del especialista ``policy``.

    :param policies: Libro de politicas.
    :type policies: app.policies.PolicyBook
    :param vacations: Calculo de vacaciones por empleado (Adenda 1); si
        falta, el especialista solo tiene ``search_policy``.
    :type vacations: app.vacations.VacationBook | None
    :return: ``search_policy`` y, con ``vacations``, ``vacation_days``.
    :rtype: dict[str, collections.abc.Callable]
    """
    tools: dict[str, ToolFunc] = {
        TOOL_SEARCH_POLICY: lambda args: policies.search_policy(
            str(args.get("topic", "")).strip()
        ),
    }
    if vacations is not None:
        tools[TOOL_VACATION_DAYS] = lambda args: vacations.vacation_days(
            str(args.get("employee_id", "")).strip()
        )
    return tools


def prefetch_list(prefetch: Prefetch | list[Prefetch] | None) -> list[Prefetch]:
    """Normaliza ``prefetch`` a una lista de ``(herramienta, args)``.

    :param prefetch: Una tupla, una lista de tuplas o ``None``.
    :type prefetch: tuple[str, dict] | list[tuple[str, dict]] | None
    :return: Lista en el orden en que se ejecutan.
    :rtype: list[tuple[str, dict]]
    """
    if prefetch is None:
        return []
    if isinstance(prefetch, tuple):
        return [prefetch]
    return list(prefetch)


def safe_tool_name(name: str, known: Iterable[str] = KNOWN_TOOLS) -> str:
    """Devuelve un nombre de herramienta seguro para el log y la traza.

    El nombre lo manda el modelo y puede traer cualquier texto: solo se
    repite si es una herramienta conocida; si no, se usa
    ``UNKNOWN_TOOL_KIND``.

    :param name: Nombre que pidio el modelo.
    :type name: str
    :param known: Herramientas conocidas; por omision todas las del
        producto (un especialista pasa solo las suyas).
    :type known: collections.abc.Iterable[str]
    :return: El mismo nombre si es conocido o ``UNKNOWN_TOOL_KIND``.
    :rtype: str
    """
    return name if name in tuple(known) else UNKNOWN_TOOL_KIND


def audit_args(tool: str, args: dict[str, Any]) -> dict[str, str]:
    """Filtra y recorta los argumentos de una herramienta para el log.

    Solo pasan los argumentos esperados de las herramientas conocidas,
    convertidos a texto, sin PII y truncados, para no filtrar datos de
    mas.

    :param tool: Nombre de la herramienta.
    :type tool: str
    :param args: Argumentos que pidio el modelo.
    :type args: dict[str, Any]
    :return: Argumentos seguros para registrar.
    :rtype: dict[str, str]
    """
    allowed = AUDITED_ARGS.get(tool, ())
    return {
        key: redact_pii(str(args[key])).text[:MAX_AUDIT_ARG_CHARS]
        for key in allowed
        if key in args
    }


def parse_decision(raw: str) -> dict[str, Any] | None:
    """Extrae la decision JSON del texto del modelo.

    Primero intenta el texto completo; si no es JSON (un modelo real
    puede agregar texto alrededor), usa el primer objeto JSON que
    aparezca.

    :param raw: Texto del modelo.
    :type raw: str
    :return: Diccionario de la decision o ``None`` si no hay uno.
    :rtype: dict[str, Any] | None
    """
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        data = _first_json_object(raw)
    return data if isinstance(data, dict) else None


def _first_json_object(raw: Any) -> Any:
    """Busca el primer objeto JSON dentro de un texto.

    :param raw: Texto del modelo.
    :type raw: Any
    :return: El objeto encontrado o ``None``.
    :rtype: Any
    """
    if not isinstance(raw, str):
        return None
    decoder = json.JSONDecoder()
    start = raw.find("{")
    while start != -1:
        try:
            return decoder.raw_decode(raw, start)[0]
        except json.JSONDecodeError:
            start = raw.find("{", start + 1)
    return None


@dataclass
class RunState:  # pylint: disable=too-many-instance-attributes
    """Estado de una corrida: modelo, ruta y lo acumulado.

    :param model: Modelo elegido para esta peticion.
    :type model: app.completion.Model
    :param route: Motivo del enrutador de costo.
    :type route: str
    :param request_id: Id de la peticion, para log y trazas.
    :type request_id: str
    :param client: Cliente que pregunta, para log y trazas.
    :type client: str
    :param specialist: Especialista que corre (spec 06).
    :type specialist: str
    :param supervisor_route: Motivo del supervisor (spec 06).
    :type supervisor_route: str
    """

    model: Model
    route: str
    request_id: str = NO_REQUEST_ID
    client: str = NO_CLIENT
    specialist: str = DEFAULT_AGENT_NAME
    supervisor_route: str = NO_ROUTE
    input_tokens: int = 0
    output_tokens: int = 0
    cached_calls: int = 0
    cost_usd: float = 0.0
    tools_used: list[str] = field(default_factory=list)
    policy_texts: list[str] = field(default_factory=list)
    vacation_results: list[dict[str, Any]] = field(default_factory=list)
    outcome: dict[str, Any] = field(default_factory=dict)

    def add(
        self,
        completion: Completion,
        prices: PriceTable,
        model_name: str | None = None,
    ) -> None:
        """Suma tokens y costo de una llamada al modelo.

        Una llamada cacheada suma tokens y ``cached_calls``, pero no
        cuesta.

        :param completion: Respuesta de la llamada.
        :type completion: app.completion.Completion
        :param prices: Tabla de precios.
        :type prices: app.pricing.PriceTable
        :param model_name: Modelo con el que se cobra; por omision el
            del especialista (el supervisor usa ``MODEL_SMALL``).
        :type model_name: str | None
        """
        self.input_tokens += completion.input_tokens
        self.output_tokens += completion.output_tokens
        if completion.cached:
            self.cached_calls += 1
            return
        self.cost_usd += prices.cost(
            model_name or self.model.name,
            completion.input_tokens,
            completion.output_tokens,
        )

    def trace_metadata(self, **extra: str) -> dict[str, str]:
        """Metadatos comunes de las trazas de esta corrida.

        :param extra: Campos adicionales, por ejemplo ``model``.
        :type extra: str
        :return: ``request_id``, ``client`` y los campos extra.
        :rtype: dict[str, str]
        """
        return {"request_id": self.request_id, "client": self.client, **extra}

    def result(self, answer: str, steps: int, stopped: str) -> dict[str, Any]:
        """Arma el diccionario de resultado de la corrida.

        :param answer: Texto de la respuesta.
        :type answer: str
        :param steps: Pasos usados.
        :type steps: int
        :param stopped: ``answer`` o ``max_steps``.
        :type stopped: str
        :return: Resultado de la corrida.
        :rtype: dict[str, Any]
        """
        return {
            "answer": answer,
            "steps": steps,
            "tools_used": list(self.tools_used),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "stopped": stopped,
            "model": self.model.name,
            "route": self.route,
            "cached_calls": self.cached_calls,
            "cost_usd": self.cost_usd,
            "specialist": self.specialist,
            "supervisor_route": self.supervisor_route,
            "policy_texts": list(self.policy_texts),
            "vacation_results": [dict(r) for r in self.vacation_results],
        }


@dataclass(frozen=True)
class Seed:
    """Llamada al modelo hecha antes del especialista (el supervisor).

    :param completion: Respuesta de la llamada.
    :type completion: app.completion.Completion
    :param model_name: Modelo con el que se cobra.
    :type model_name: str
    """

    completion: Completion
    model_name: str


class Agent:  # pylint: disable=too-many-instance-attributes
    """Especialista que orquesta modelo y herramientas.

    En cada paso, envia los mensajes al modelo e interpreta
    su respuesta JSON. Si el modelo pide una herramienta, la
    ejecuta y agrega el resultado. Si responde directamente,
    el bucle termina. Si se alcanza el tope de pasos, devuelve
    el mensaje de fallback.

    :param directory: Directorio de empleados (sus departamentos validan
        ``search_by_department``).
    :type directory: app.directory.Directory
    :param prices: Tabla de precios por modelo.
    :type prices: app.pricing.PriceTable
    :param max_steps: Tope de pasos del bucle.
    :type max_steps: int
    :param logger: Logger de eventos; si falta, no se registra nada.
    :type logger: app.logs.JsonLogger | None
    :param tracer: Trazador; si falta, no se traza nada.
    :type tracer: app.tracing.Tracer | None
    :param audit: Auditoria de seguridad; si falta, no se registra nada.
    :type audit: app.security.Audit | None
    :param name: Nombre del especialista (spec 06).
    :type name: str
    :param tools: Registro propio de herramientas; por omision las de
        ``directory``.
    :type tools: collections.abc.Mapping[str, collections.abc.Callable] | None
    :param system_prompt: Prompt de sistema; sin el, el gateway pone el
        de ``directory``.
    :type system_prompt: str | None
    """

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        directory: Directory,
        prices: PriceTable,
        max_steps: int = 3,
        logger: JsonLogger | NullLogger | None = None,
        tracer: Tracer | None = None,
        audit: Audit | None = None,
        name: str = DEFAULT_AGENT_NAME,
        tools: Mapping[str, ToolFunc] | None = None,
        system_prompt: str | None = None,
    ) -> None:
        """Inicializa el agente con sus dependencias.

        Los parametros despues de ``max_steps`` son opcionales, asi el
        agente se construye igual que en las sesiones anteriores.

        :param directory: Directorio de empleados.
        :type directory: app.directory.Directory
        :param prices: Tabla de precios por modelo.
        :type prices: app.pricing.PriceTable
        :param max_steps: Tope de pasos del bucle.
        :type max_steps: int
        :param logger: Logger de eventos.
        :type logger: app.logs.JsonLogger | None
        :param tracer: Trazador; por omision uno con trazas apagadas.
        :type tracer: app.tracing.Tracer | None
        :param audit: Auditoria de seguridad; por omision una que no
            registra nada.
        :type audit: app.security.Audit | None
        :param name: Nombre del especialista.
        :type name: str
        :param tools: Registro propio de herramientas.
        :type tools: collections.abc.Mapping[str, collections.abc.Callable] | None
        :param system_prompt: Prompt de sistema del especialista.
        :type system_prompt: str | None
        """
        self._directory = directory
        self._prices = prices
        self._max_steps = max_steps
        self._logger = logger if logger is not None else NullLogger()
        self._tracer = tracer if tracer is not None else Tracer(TracingOptions())
        self._audit = audit if audit is not None else NullAudit()
        self.name = name
        self._tools = dict(tools) if tools is not None else directory_tools(directory)
        self._system_prompt = system_prompt

    @property
    def audit(self) -> Audit:
        """Auditoria de seguridad del agente; la API la reusa en la entrada.

        :return: Auditoria inyectada o la que no registra nada.
        :rtype: app.security.Audit
        """
        return self._audit

    @property
    def tool_names(self) -> tuple[str, ...]:
        """Herramientas que puede usar este especialista.

        :return: Nombres del registro propio.
        :rtype: tuple[str, ...]
        """
        return tuple(self._tools)

    def run(  # pylint: disable=too-many-arguments,too-many-locals
        self,
        question: str,
        history: list[dict[str, str]] | None = None,
        *,
        model: Model,
        request_id: str = NO_REQUEST_ID,
        route: str = NO_ROUTE,
        client: str = NO_CLIENT,
        supervisor_route: str = NO_ROUTE,
        prefetch: Prefetch | list[Prefetch] | None = None,
        seed: Seed | None = None,
    ) -> dict[str, Any]:
        """Ejecuta el bucle del agente para una pregunta.

        :param question: Pregunta del usuario (ya limpia).
        :type question: str
        :param history: Historial previo (ya recortado por la ventana).
        :type history: list[dict[str, str]] | None
        :param model: Modelo elegido para esta peticion.
        :type model: app.completion.Model
        :param request_id: Id de la peticion, para log y trazas.
        :type request_id: str
        :param route: Motivo del enrutador de costo.
        :type route: str
        :param client: Cliente que pregunta (nunca su clave), para
            ``audit``, ``agent_run`` y los metadatos de las trazas.
        :type client: str
        :param supervisor_route: Motivo del supervisor (spec 06).
        :type supervisor_route: str
        :param prefetch: Herramienta y argumentos que se ejecutan en
            codigo antes de la pregunta; su resultado va antes de ella.
        :type prefetch: tuple[str, dict] | list[tuple[str, dict]] | None
        :param seed: Llamada del supervisor, que suma tokens y costo.
        :type seed: Seed | None
        :return: Diccionario con answer, steps, tools_used,
            input_tokens, output_tokens, stopped, model, route,
            cached_calls, cost_usd, specialist, supervisor_route y
            policy_texts (politicas consultadas).
        :rtype: dict[str, Any]
        :raises app.completion.ModelUnavailable: Si el modelo falla.
        """
        state = RunState(
            model=model,
            route=route,
            request_id=request_id,
            client=client,
            specialist=self.name,
            supervisor_route=supervisor_route,
        )
        if seed is not None:
            state.add(seed.completion, self._prices, seed.model_name)
        metadata = state.trace_metadata(model=model.name)
        traced_loop = self._tracer.traceable("agent_run", "chain", metadata)(
            self._summarized_loop
        )
        traced_loop(question, history or [], state, prefetch)
        result = state.outcome
        self._logger.emit(
            "agent_run",
            request_id,
            client=client,
            question_chars=len(question),
            history_messages=len(history or []),
            steps=result["steps"],
            tools=list(result["tools_used"]),
            input_tokens=result["input_tokens"],
            output_tokens=result["output_tokens"],
            stopped=result["stopped"],
            model=result["model"],
            route=result["route"],
            cached_calls=result["cached_calls"],
            cost_usd=result["cost_usd"],
            specialist=result["specialist"],
            supervisor_route=result["supervisor_route"],
        )
        return result

    def _summarized_loop(
        self,
        question: str,
        history: list[dict[str, str]],
        state: RunState,
        prefetch: Prefetch | list[Prefetch] | None,
    ) -> dict[str, Any]:
        """Corre el bucle, guarda el resultado y devuelve solo un resumen.

        La respuesta queda en ``state.outcome``; la salida de la traza
        no lleva texto (la validacion la hace despues el revisor).

        :param question: Pregunta del usuario (ya limpia).
        :type question: str
        :param history: Historial previo (ya limpio).
        :type history: list[dict[str, str]]
        :param state: Estado de la corrida.
        :type state: RunState
        :param prefetch: Herramienta a ejecutar antes de la pregunta.
        :type prefetch: tuple[str, dict] | list[tuple[str, dict]] | None
        :return: Pasos, herramientas, motivo de parada y especialista.
        :rtype: dict[str, Any]
        """
        state.outcome = self._loop(question, history, state, prefetch)
        return {
            "specialist": state.specialist,
            "steps": state.outcome["steps"],
            "tools": list(state.outcome["tools_used"]),
            "stopped": state.outcome["stopped"],
        }

    def _start_messages(
        self,
        question: str,
        history: list[dict[str, str]],
        state: RunState,
        prefetch: Prefetch | list[Prefetch] | None,
    ) -> list[dict[str, str]]:
        """Arma los mensajes iniciales del especialista.

        Orden: prompt de sistema (si lo hay), historial, resultado de la
        herramienta ejecutada en codigo (si la hay) y la pregunta.

        :param question: Pregunta del usuario.
        :type question: str
        :param history: Historial previo.
        :type history: list[dict[str, str]]
        :param state: Estado de la corrida.
        :type state: RunState
        :param prefetch: Herramienta a ejecutar antes de la pregunta.
        :type prefetch: tuple[str, dict] | list[tuple[str, dict]] | None
        :return: Mensajes para la primera llamada.
        :rtype: list[dict[str, str]]
        """
        messages: list[dict[str, str]] = []
        if self._system_prompt:
            messages.append({"role": "system", "content": self._system_prompt})
        messages.extend(history)
        # Adenda 1: puede haber varias consultas en codigo, en orden.
        for tool_name, args in prefetch_list(prefetch):
            messages.append(self._tool_message(tool_name, args, state))
        messages.append({"role": "user", "content": question})
        return messages

    def _tool_message(
        self, tool_name: str, args: dict[str, Any], state: RunState
    ) -> dict[str, str]:
        """Ejecuta una herramienta y arma el mensaje con su resultado.

        :param tool_name: Herramienta pedida.
        :type tool_name: str
        :param args: Argumentos de la herramienta.
        :type args: dict[str, Any]
        :param state: Estado de la corrida.
        :type state: RunState
        :return: Mensaje ``user`` con ``TOOL_RESULT_PREFIX``.
        :rtype: dict[str, str]
        """
        tool_result = self._call_tool(tool_name, args, state)
        # ``tools_used`` llega a ``agent_run``: nunca el texto crudo.
        state.tools_used.append(safe_tool_name(tool_name, self._tools))
        return {
            "role": "user",
            "content": TOOL_RESULT_PREFIX
            + json.dumps(tool_result, ensure_ascii=False),
        }

    def _loop(
        self,
        question: str,
        history: list[dict[str, str]],
        state: RunState,
        prefetch: Prefetch | list[Prefetch] | None = None,
    ) -> dict[str, Any]:
        """Corre las vueltas del bucle hasta responder o llegar al tope.

        :param question: Pregunta del usuario.
        :type question: str
        :param history: Historial previo de la conversacion.
        :type history: list[dict[str, str]]
        :param state: Estado de la corrida (con ``request_id`` y
            ``client``).
        :type state: RunState
        :param prefetch: Herramienta a ejecutar antes de la pregunta.
        :type prefetch: tuple[str, dict] | list[tuple[str, dict]] | None
        :return: Resultado de la corrida.
        :rtype: dict[str, Any]
        """
        metadata = state.trace_metadata(model=state.model.name)
        complete = self._tracer.traceable("llm", "llm", metadata)(
            state.model.complete
        )
        messages = self._start_messages(question, history, state, prefetch)

        for step in range(1, self._max_steps + 1):
            completion = complete(messages)
            state.add(completion, self._prices)
            parsed = parse_decision(completion.text)

            if parsed is None:
                # JSON invalido, cuenta como paso fallido
                continue
            if "answer" in parsed:
                return state.result(str(parsed["answer"]), step, STOPPED_ANSWER)
            if "tool" in parsed:
                args = parsed.get("args")
                messages.append(
                    self._tool_message(
                        str(parsed["tool"]),
                        args if isinstance(args, dict) else {},
                        state,
                    )
                )

        # Se alcanzo el tope sin respuesta
        return state.result(FALLBACK_MESSAGE, self._max_steps, STOPPED_MAX_STEPS)

    def _call_tool(self, name: str, args: dict[str, Any], state: RunState) -> Any:
        """Registra en ``audit``, valida e invoca una herramienta.

        Si la herramienta no es de este especialista o
        ``validate_tool_args`` rechaza el argumento, no se ejecuta: se
        registra ``security`` (``control=tool_args``) y el modelo recibe
        un error que no repite el valor.

        :param name: Nombre de la herramienta.
        :type name: str
        :param args: Argumentos de la herramienta.
        :type args: dict[str, Any]
        :param state: Estado de la corrida (``request_id`` y ``client``).
        :type state: RunState
        :return: Resultado de la herramienta o ``{"error": ...}``.
        :rtype: Any
        """
        # El nombre lo inventa el modelo: solo se repite si es de este agente.
        tool = safe_tool_name(name, self._tools)
        if tool == UNKNOWN_TOOL_KIND:
            reason: str | None = UNKNOWN_TOOL_REASON
        else:
            reason = validate_tool_args(tool, args, self._directory.departments)
        # Adenda 1: ``vacation_days`` con formato invalido no se llama, asi
        # que no deja ``audit`` y el modelo recibe el error de la spec.
        vacation_rejected = tool == TOOL_VACATION_DAYS and reason is not None
        if not vacation_rejected:
            self._logger.emit(
                "audit",
                state.request_id,
                client=state.client,
                action="tool_call",
                tool=tool,
                args=audit_args(tool, args),
            )
        if reason is not None:
            self._audit.record(
                state.request_id,
                state.client,
                STAGE_OUTPUT,
                CONTROL_TOOL_ARGS,
                [tool],
            )
            if vacation_rejected:
                return {"error": EMPLOYEE_NOT_FOUND}
            return {"error": INVALID_ARGS_TEMPLATE.format(tool=tool, reason=reason)}
        metadata = state.trace_metadata()
        traced = self._tracer.traceable(tool, "tool", metadata)(self._tools[tool])
        result = traced(args)
        self._remember(tool, result, state)
        return result

    @staticmethod
    def _remember(tool: str, result: Any, state: RunState) -> None:
        """Guarda los datos consultados que usa el revisor.

        :param tool: Herramienta ejecutada.
        :type tool: str
        :param result: Resultado de la herramienta.
        :type result: Any
        :param state: Estado de la corrida.
        :type state: RunState
        """
        if (
            tool == TOOL_SEARCH_POLICY
            and isinstance(result, dict)
            and isinstance(result.get("text"), str)
        ):
            state.policy_texts.append(result["text"])
        if tool == TOOL_VACATION_DAYS and is_vacation_result(result):
            state.vacation_results.append(dict(result))
