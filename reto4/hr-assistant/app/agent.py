"""Agente único con bucle con tope y protocolo JSON (ADR 0003 y 0007).

Además del bucle, aplica la ventana de historial y suma el costo de cada
llamada al modelo con la tabla de precios; una llamada cacheada cuesta 0. Si
recibe un tracer, la corrida, cada llamada al modelo y cada herramienta quedan
como trazas con el ``request_id`` (ADR 0005).
"""

import json
from dataclasses import dataclass, field

TOOL_RESULT_PREFIX = "Resultado de la herramienta: "
CAP_MESSAGE = (
    "No pude completar la respuesta. Intenta con una pregunta más concreta."
)
TOOL_PARAMETERS = {
    "get_employee": ("employee_id",),
    "search_by_department": ("department",),
}


@dataclass
class AgentResult:  # pylint: disable=too-many-instance-attributes
    """Resultado de una pregunta respondida por el agente.

    :param answer: Respuesta final en español
    :type answer: str
    :param steps: Llamadas hechas al modelo
    :type steps: int
    :param tools_used: Herramientas ejecutadas, en orden
    :type tools_used: list[str]
    :param tool_calls: Herramientas con sus argumentos, para el evento ``audit``
    :type tool_calls: list[dict]
    :param input_tokens: Suma de tokens de entrada
    :type input_tokens: int
    :param output_tokens: Suma de tokens de salida
    :type output_tokens: int
    :param model: Nombre del modelo que respondió
    :type model: str
    :param cached_calls: Llamadas que salieron de la caché del gateway
    :type cached_calls: int
    :param cost_usd: Suma del costo de las llamadas, en USD
    :type cost_usd: float
    :param stopped: Si el bucle se detuvo por el tope de vueltas
    :type stopped: bool
    """

    answer: str
    steps: int = 0
    tools_used: list = field(default_factory=list)
    tool_calls: list = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    cached_calls: int = 0
    cost_usd: float = 0.0
    stopped: bool = False


class ToolCallError(ValueError):
    """La salida del modelo no es una petición de herramienta válida."""


def apply_window(history, window):
    """Deja solo los últimos ``window`` mensajes del historial.

    :param history: Mensajes previos con ``role`` y ``content``
    :type history: list[dict]
    :param window: Mensajes que se conservan; ``None`` conserva todos
    :type window: int or None
    :return: Los mensajes conservados, copiados
    :rtype: list[dict]
    """
    if window is None:
        kept = list(history)
    elif window <= 0:
        kept = []
    else:
        kept = list(history)[-window:]
    return [
        {"role": message["role"], "content": message["content"]}
        for message in kept
    ]


class Agent:
    """Agente que alterna entre el modelo y las herramientas del directorio.

    :param model: Modelo con el método ``complete(messages)``
    :type model: app.llm.LanguageModel
    :param directory: Directorio de empleados de solo lectura
    :type directory: app.directory.EmployeeDirectory
    :param max_steps: Tope de llamadas al modelo
    :type max_steps: int
    :param prices: Tabla de precios; sin ella el costo es 0
    :type prices: app.pricing.PriceTable or None
    :param history_window: Mensajes de historial que se mandan; ``None``: todos
    :type history_window: int or None
    :param tracer: Tracer de la corrida, el modelo y las herramientas;
        ``None``: sin trazas
    :type tracer: app.observability.NullTracer or None
    :param request_id: Id de la petición, para los metadatos de las trazas
    :type request_id: str
    :param client: Nombre del cliente, para los metadatos de las trazas
    :type client: str or None
    """

    def __init__(  # pylint: disable=too-many-arguments
        self, model, directory, max_steps, *, prices=None, history_window=None,
        tracer=None, request_id="", client=None,
    ):
        self._model = model
        self._directory = directory
        self._max_steps = max_steps
        self._prices = prices
        self._history_window = history_window
        self._tracer = tracer
        # Etiquetas de las trazas: id de la petición y nombre del cliente.
        self._trace_tags = (request_id, client)

    def _trace(self, function, name, run_type):
        """Envuelve ``function`` con el tracer, si hay uno.

        :param function: Función que se traza
        :type function: callable
        :param name: Nombre de la traza
        :type name: str
        :param run_type: Tipo de traza (``chain``, ``llm`` o ``tool``)
        :type run_type: str
        :return: La función trazada o la original
        :rtype: callable
        """
        if self._tracer is None:
            return function
        request_id, client = self._trace_tags
        return self._tracer.wrap(function, name, run_type, request_id, client=client)

    def _execute_tool(self, decision):
        """Ejecuta la herramienta pedida por el modelo.

        :param decision: Objeto con ``tool`` y ``args``
        :type decision: dict
        :return: Nombre de la herramienta y su resultado en texto
        :rtype: tuple[str, str]
        :raises ToolCallError: Si la herramienta o los argumentos son inválidos
        """
        name = decision.get("tool")
        if name not in TOOL_PARAMETERS:
            raise ToolCallError(f"Error: la herramienta {name!r} no existe.")
        args = decision.get("args")
        if not isinstance(args, dict):
            raise ToolCallError("Error: 'args' debe ser un objeto JSON.")
        expected = TOOL_PARAMETERS[name]
        if set(args) != set(expected):
            raise ToolCallError(
                f"Error: {name} requiere exactamente los argumentos "
                f"{', '.join(expected)}."
            )
        values = [args[parameter] for parameter in expected]
        if not all(isinstance(value, str) and value.strip() for value in values):
            raise ToolCallError(f"Error: los argumentos de {name} deben ser texto.")
        tool = self._trace(getattr(self._directory, name), name, "tool")
        return name, tool(*values)

    def _handle_reply(self, text, result):
        """Interpreta una respuesta del modelo.

        :param text: Texto devuelto por el modelo
        :type text: str
        :param result: Resultado parcial que se actualiza con herramientas usadas
        :type result: AgentResult
        :return: La respuesta final, o ``None`` y el mensaje para el modelo
        :rtype: tuple[str or None, str or None]
        """
        try:
            decision = json.loads(text)
        except (TypeError, ValueError):
            return None, "Error: la respuesta no es un objeto JSON válido."
        if not isinstance(decision, dict):
            return None, "Error: la respuesta debe ser un objeto JSON."
        if "answer" in decision and isinstance(decision["answer"], str):
            return decision["answer"], None
        if "tool" not in decision:
            return None, "Error: falta 'answer' o 'tool' en la respuesta."
        try:
            name, output = self._execute_tool(decision)
        except ToolCallError as error:
            return None, str(error)
        result.tools_used.append(name)
        result.tool_calls.append({"tool": name, "args": dict(decision["args"])})
        return None, output

    def _account(self, reply, result):
        """Suma tokens, costo y llamadas cacheadas de una respuesta.

        :param reply: Respuesta del modelo
        :type reply: app.llm.ModelReply
        :param result: Resultado parcial que se actualiza
        :type result: AgentResult
        """
        result.input_tokens += reply.input_tokens
        result.output_tokens += reply.output_tokens
        result.model = reply.model
        if reply.cached:
            result.cached_calls += 1
        elif self._prices is not None:
            result.cost_usd += self._prices.cost(
                reply.model, reply.input_tokens, reply.output_tokens
            )

    def run(self, question, history):
        """Responde una pregunta usando el modelo y las herramientas.

        La ventana se aplica solo al historial del cliente, antes de agregar la
        pregunta: los mensajes del bucle en curso nunca se recortan.

        :param question: Pregunta de la persona
        :type question: str
        :param history: Mensajes previos con ``role`` y ``content``
        :type history: list[dict]
        :return: Respuesta, pasos, herramientas, tokens y costo
        :rtype: AgentResult
        :raises app.llm.ModelUnavailableError: Si el modelo real no responde
        """
        return self._trace(self._run, "agent", "chain")(question, history)

    def _run(self, question, history):
        """Bucle del agente; :meth:`run` lo envuelve en una traza.

        :param question: Pregunta de la persona
        :type question: str
        :param history: Mensajes previos con ``role`` y ``content``
        :type history: list[dict]
        :return: Respuesta, pasos, herramientas, tokens y costo
        :rtype: AgentResult
        :raises app.llm.ModelUnavailableError: Si el modelo real no responde
        """
        messages = apply_window(history, self._history_window)
        messages.append({"role": "user", "content": question})
        result = AgentResult(answer=CAP_MESSAGE)
        complete = self._trace(self._model.complete, "model", "llm")
        for step in range(1, self._max_steps + 1):
            reply = complete(messages)
            result.steps = step
            self._account(reply, result)
            answer, feedback = self._handle_reply(reply.text, result)
            if answer is not None:
                result.answer = answer
                return result
            messages.append({"role": "assistant", "content": reply.text})
            messages.append(
                {"role": "user", "content": TOOL_RESULT_PREFIX + feedback}
            )
        result.answer = CAP_MESSAGE
        result.stopped = True
        return result
