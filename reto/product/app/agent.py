"""Agente con bucle acotado que usa herramientas de solo lectura del directorio.

En cada vuelta el modelo pide una herramienta o responde. Las salidas que no
cumplen el protocolo se devuelven al modelo como error y consumen una vuelta;
nunca se lanzan excepciones hacia la API.
"""

import json
from dataclasses import dataclass, field

from app.clock import SystemClock
from app.directory import EmployeeDirectory
from app.llm import FAKE_MODEL_NAME, LLM, TOOL_RESULT_PREFIX
from app.pricing import FREE_PRICES, PriceTable
from app.telemetry import NullRequestLog, RunSummary
from app.tracing import NoopTracer

STOPPED_ANSWER = "answer"
STOPPED_MAX_STEPS = "max_steps"
MILLISECONDS = 1000
LATENCY_DECIMALS = 3

CAP_MESSAGE = (
    "No pude completar la respuesta. Intenta con una pregunta más concreta."
)

SYSTEM_PROMPT = (
    "Eres el asistente de Recursos Humanos. Responde siempre con un único "
    "objeto JSON. Para pedir una herramienta: "
    '{"tool": "<nombre>", "args": {...}}. Para responder: '
    '{"answer": "<respuesta en español>"}. Herramientas disponibles: '
    "get_employee(employee_id) devuelve un empleado por id, por ejemplo "
    "EMP-0004; search_by_department(department) devuelve los empleados de un "
    "departamento. El resultado de una herramienta llega en un mensaje que "
    f"empieza con '{TOOL_RESULT_PREFIX.strip()}'. "
    "Solo das los datos que devuelven tus herramientas: id, nombre, "
    "departamento, puesto, fecha de ingreso y estado. Nunca inventes datos. Si "
    "te piden otro dato de una persona (teléfono, correo, dirección, salario u "
    "otro), responde exactamente: "
    '{"answer": "No tengo ese dato en el directorio."}'
)

# Cada herramienta declara el unico argumento de texto que acepta.
TOOL_ARGUMENTS = {
    "get_employee": "employee_id",
    "search_by_department": "department",
}


@dataclass
class AgentResult:  # pylint: disable=too-many-instance-attributes
    """Resultado de una ejecucion del agente.

    :param answer: Respuesta final en español
    :type answer: str
    :param steps: Vueltas del bucle consumidas
    :type steps: int
    :param tools_used: Herramientas ejecutadas, en orden
    :type tools_used: list[str]
    :param input_tokens: Suma de tokens de entrada
    :type input_tokens: int
    :param output_tokens: Suma de tokens de salida
    :type output_tokens: int
    :param stopped: Motivo de fin: ``answer`` o ``max_steps``
    :type stopped: str
    :param model: Nombre del modelo usado
    :type model: str
    :param cost_usd: Costo en USD; las llamadas cacheadas no suman
    :type cost_usd: float
    :param cached_calls: Llamadas respondidas por la cache del gateway
    :type cached_calls: int
    """

    answer: str
    steps: int = 0
    tools_used: list = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    stopped: str = STOPPED_MAX_STEPS
    model: str = FAKE_MODEL_NAME
    cost_usd: float = 0.0
    cached_calls: int = 0


@dataclass(frozen=True)
class CostOptions:
    """Lo que el agente necesita para medir y recortar el costo.

    :param model: Nombre del modelo enrutado (decide el precio)
    :type model: str
    :param route: Motivo del enrutador (solo para el log)
    :type route: str
    :param history_window: Mensajes de historial que se mandan; ``None``
        manda todos
    :type history_window: int or None
    :param prices: Tabla de precios por modelo
    :type prices: app.pricing.PriceTable
    """

    model: str = FAKE_MODEL_NAME
    route: str = ""
    history_window: int | None = None
    prices: PriceTable = FREE_PRICES

    def window(self, history: list) -> list:
        """Recorta el historial a los ultimos ``history_window`` mensajes.

        :param history: Mensajes previos del cliente
        :type history: list[dict]
        :return: Los mensajes que se mandan al modelo
        :rtype: list[dict]
        """
        if self.history_window is None:
            return list(history)
        if self.history_window == 0:
            # ``history[-0:]`` devolveria todo el historial.
            return []
        return list(history[-self.history_window:])

    def call_cost(self, completion) -> float:
        """Costo de una llamada: 0 si vino de la cache.

        :param completion: Respuesta del modelo
        :type completion: app.completion.Completion
        :return: Costo en USD
        :rtype: float
        """
        if completion.cached:
            return 0.0
        return self.prices.cost(
            self.model, completion.input_tokens, completion.output_tokens
        )


class ToolCallError(ValueError):
    """La salida del modelo no es una peticion valida."""


class Agent:  # pylint: disable=too-few-public-methods,too-many-instance-attributes
    """Agente unico con tope de vueltas.

    Se crea uno por peticion; no guarda estado entre ejecuciones.

    :param llm: Modelo que cumple el protocolo ``LLM``
    :type llm: LLM
    :param directory: Directorio de empleados de solo lectura
    :type directory: EmployeeDirectory
    :param max_steps: Tope de vueltas del bucle (>= 1)
    :type max_steps: int
    :param telemetry: Emisor de eventos ligado a la peticion; por omision
        descarta los eventos
    :type telemetry: app.telemetry.RequestLog or None
    :param tracer: Trazador de corridas, modelo y herramientas; por omision
        uno apagado
    :type tracer: app.tracing.NoopTracer or None
    :param clock: Reloj para medir ``latency_ms``; por omision el del sistema
    :type clock: app.clock.Clock or None
    :param environment: ``development`` o ``production``, para los metadatos
        y tags de la traza; por omision no se reporta
    :type environment: str or None
    :param options: Modelo, motivo, ventana y precios (ver ``CostOptions``);
        por omision ``fake``, sin recorte y sin costo
    :type options: dict
    """

    def __init__(  # pylint: disable=too-many-arguments
        self,
        llm: LLM,
        directory: EmployeeDirectory,
        max_steps: int,
        *,
        telemetry=None,
        tracer=None,
        clock=None,
        environment=None,
        **options,
    ):
        self._llm = llm
        self._directory = directory
        self._max_steps = max_steps
        self._log = telemetry if telemetry is not None else NullRequestLog()
        self._tracer = tracer if tracer is not None else NoopTracer()
        self._clock = clock if clock is not None else SystemClock()
        self._environment = environment
        self._cost = CostOptions(**options)

    def run(self, question: str, history: list) -> AgentResult:
        """Responde una pregunta y registra el resumen de la corrida.

        El evento ``agent_run`` solo lleva conteos, latencia y costo, nunca el
        texto de la pregunta ni de la respuesta.

        :param question: Pregunta de la persona
        :type question: str
        :param history: Mensajes previos con ``role`` y ``content``
        :type history: list[dict]
        :return: Respuesta, vueltas, herramientas, tokens y motivo de fin
        :rtype: AgentResult
        """
        sent_history = self._cost.window(history)
        traced_run = self._trace(self._annotated_loop, "agent_run")
        started = self._clock.monotonic()
        result = traced_run(question, sent_history)
        elapsed = self._clock.monotonic() - started
        self._log.agent_run(
            RunSummary(
                question_chars=len(question),
                history_messages=len(history),
                steps=result.steps,
                tools=list(result.tools_used),
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                stopped=result.stopped,
                model=result.model,
                route=self._cost.route,
                history_sent=len(sent_history),
                cached_calls=result.cached_calls,
                cost_usd=result.cost_usd,
                latency_ms=round(elapsed * MILLISECONDS, LATENCY_DECIMALS),
            )
        )
        return result

    def _annotated_loop(self, question: str, history: list) -> AgentResult:
        """Corre el bucle y agrega su ``cost_usd`` a la traza ``agent_run``.

        El costo solo se conoce al terminar; se agrega dentro de la funcion
        trazada para que quede en los metadatos de esa corrida. Un trazador
        sin ``annotate`` (por ejemplo, un doble de pruebas) se respeta.

        :param question: Pregunta de la persona
        :type question: str
        :param history: Mensajes previos ya recortados a la ventana
        :type history: list[dict]
        :return: El resultado del bucle
        :rtype: AgentResult
        """
        result = self._loop(question, history)
        annotate = getattr(self._tracer, "annotate", None)
        if annotate is not None:
            annotate(cost_usd=result.cost_usd)
        return result

    def _trace(self, func, name: str):
        """Envuelve una funcion con el trazador y el contexto de la peticion.

        Los metadatos son ``request_id``, ``client`` (el nombre ligado al log;
        la clave nunca llega aqui), ``model``, ``route`` y ``environment``.

        :param func: Funcion a trazar
        :type func: callable
        :param name: Nombre de la traza
        :type name: str
        :return: La funcion envuelta
        :rtype: callable
        """
        return self._tracer.trace(
            func,
            name=name,
            request_id=self._log.request_id,
            client=self._log.client,
            model=self._cost.model,
            route=self._cost.route or None,
            environment=self._environment,
        )

    def _loop(self, question: str, history: list) -> AgentResult:
        """Ejecuta el bucle acotado de modelo y herramientas.

        :param question: Pregunta de la persona
        :type question: str
        :param history: Mensajes previos ya recortados a la ventana
        :type history: list[dict]
        :return: Respuesta, vueltas, herramientas, tokens, costo y motivo de fin
        :rtype: AgentResult
        """
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(
            {"role": item["role"], "content": item["content"]} for item in history
        )
        messages.append({"role": "user", "content": question})
        complete = self._trace(self._llm.complete, "llm")
        result = AgentResult(answer=CAP_MESSAGE, model=self._cost.model)
        while result.steps < self._max_steps:
            completion = complete(messages)
            result.steps += 1
            result.input_tokens += completion.input_tokens
            result.output_tokens += completion.output_tokens
            result.cached_calls += int(completion.cached)
            result.cost_usd += self._cost.call_cost(completion)
            try:
                payload = self._parse(completion.text)
                if "answer" in payload:
                    result.answer = payload["answer"]
                    result.stopped = STOPPED_ANSWER
                    return result
                tool_output = self._call_tool(payload)
                result.tools_used.append(payload["tool"])
            except ToolCallError as error:
                tool_output = {"error": str(error)}
            messages.append({"role": "assistant", "content": completion.text})
            serialized = json.dumps(tool_output, ensure_ascii=False)
            messages.append(
                {"role": "user", "content": TOOL_RESULT_PREFIX + serialized}
            )
        return result

    @staticmethod
    def _parse(text: str) -> dict:
        """Interpreta la salida del modelo segun el protocolo.

        :param text: Texto devuelto por el modelo
        :type text: str
        :return: Objeto con ``answer`` o con ``tool`` y ``args``
        :rtype: dict
        :raises ToolCallError: Si la salida no cumple el protocolo
        """
        try:
            payload = json.loads(text)
        except (TypeError, ValueError) as error:
            raise ToolCallError("Model output is not valid JSON.") from error
        if not isinstance(payload, dict):
            raise ToolCallError("Model output must be a JSON object.")
        if "answer" in payload:
            if not isinstance(payload["answer"], str):
                raise ToolCallError("The answer must be a string.")
            return payload
        if "tool" not in payload:
            raise ToolCallError("Model output must contain 'answer' or 'tool'.")
        return payload

    def _call_tool(self, payload: dict):
        """Audita y ejecuta (con traza) la herramienta pedida por el modelo.

        Se emite un evento ``audit`` por cada herramienta pedida, tambien
        cuando la peticion no es valida (con ``ok`` en falso).

        :param payload: Peticion con ``tool`` y ``args``
        :type payload: dict
        :return: Resultado serializable de la herramienta
        :rtype: dict or list
        :raises ToolCallError: Si la herramienta o sus argumentos no son validos
        """
        tool, args = payload.get("tool"), payload.get("args")
        try:
            output = self._trace(self._execute, "tool")(payload)
        except ToolCallError:
            self._log.audit(tool=tool, args=args, ok=False)
            raise
        self._log.audit(tool=tool, args=args, ok=True)
        return output

    def _execute(self, payload: dict):
        """Ejecuta la herramienta pedida por el modelo.

        :param payload: Peticion con ``tool`` y ``args``
        :type payload: dict
        :return: Resultado serializable de la herramienta
        :rtype: dict or list
        :raises ToolCallError: Si la herramienta o sus argumentos no son validos
        """
        name = payload.get("tool")
        if name not in TOOL_ARGUMENTS:
            raise ToolCallError(f"Unknown tool: {name!r}.")
        args = payload.get("args")
        expected = TOOL_ARGUMENTS[name]
        if (
            not isinstance(args, dict)
            or set(args) != {expected}
            or not isinstance(args[expected], str)
        ):
            raise ToolCallError(
                f"Tool {name} expects args {{\"{expected}\": <string>}}."
            )
        if name == "get_employee":
            return self._directory.get_employee(args[expected])
        return self._directory.search_by_department(args[expected])
