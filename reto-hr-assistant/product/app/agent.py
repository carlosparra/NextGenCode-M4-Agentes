"""Agente con bucle de herramientas y tope de vueltas."""

import json
from dataclasses import dataclass, field

from app.llm import TOOL_RESULT_PREFIX

STOPPED_ANSWER = "answer"
STOPPED_MAX_STEPS = "max_steps"
FALLBACK_ANSWER = (
    "No pude completar la respuesta. Intenta con una pregunta más concreta."
)
SYSTEM_PROMPT = (
    "Eres un asistente de Recursos Humanos. Responde siempre con un único objeto "
    'JSON: {"tool": "<nombre>", "args": {...}} para pedir una herramienta o '
    '{"answer": "<respuesta en español>"} para responder. Herramientas:\n'
    "- get_employee(employee_id): datos laborales de un empleado.\n"
    "- search_by_department(department): empleados de un departamento.\n"
    "- get_vacation_balance(employee_id): días de vacaciones totales, tomados "
    "y disponibles.\n"
    "- department_summary(department): personas, activas, de baja y promedio "
    "de días disponibles."
)


class ToolError(Exception):
    """Error recuperable al interpretar o ejecutar una herramienta."""


@dataclass
class AgentResult:  # pylint: disable=too-many-instance-attributes
    """Resultado de una pregunta respondida por el agente.

    :param answer: Respuesta final en español
    :type answer: str
    :param steps: Número de llamadas al modelo
    :type steps: int
    :param tools_used: Herramientas ejecutadas, en orden
    :type tools_used: list[str]
    :param input_tokens: Tokens de entrada sumados entre vueltas
    :type input_tokens: int
    :param output_tokens: Tokens de salida sumados entre vueltas
    :type output_tokens: int
    :param stopped: Por qué terminó: ``"answer"`` o ``"max_steps"``
    :type stopped: str
    :param model: Nombre del modelo usado (``None`` si no se indicó)
    :type model: str or None
    :param cached_calls: Llamadas que salieron de la caché del gateway
    :type cached_calls: int
    :param billable_input_tokens: Tokens de entrada de llamadas no cacheadas
    :type billable_input_tokens: int
    :param billable_output_tokens: Tokens de salida de llamadas no cacheadas
    :type billable_output_tokens: int
    """

    answer: str
    steps: int = 0
    tools_used: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    stopped: str = STOPPED_MAX_STEPS
    model: str | None = None
    cached_calls: int = 0
    billable_input_tokens: int = 0
    billable_output_tokens: int = 0

    def add_reply(self, reply) -> None:
        """Suma los tokens de una llamada; las cacheadas no son cobrables.

        :param reply: Respuesta del modelo
        :type reply: app.llm.ModelReply
        """
        self.input_tokens += reply.input_tokens
        self.output_tokens += reply.output_tokens
        if getattr(reply, "cached", False):
            self.cached_calls += 1
            return
        self.billable_input_tokens += reply.input_tokens
        self.billable_output_tokens += reply.output_tokens


def extract_json_object(text: str) -> dict:
    """Extrae el primer objeto JSON del texto del modelo.

    Acepta JSON limpio, rodeado de texto o dentro de un bloque de código.

    :param text: Texto devuelto por el modelo
    :type text: str
    :return: Objeto del protocolo
    :rtype: dict
    :raises ToolError: Si el texto no contiene un objeto JSON válido
    """
    if not isinstance(text, str):
        raise ToolError("la respuesta no es JSON válido")
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if isinstance(data, dict):
        return data
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            candidate, _ = decoder.raw_decode(text, start)
        except ValueError:
            candidate = None
        if isinstance(candidate, dict):
            return candidate
        start = text.find("{", start + 1)
    if data is not None:
        raise ToolError("la respuesta debe ser un objeto JSON")
    raise ToolError("la respuesta no es JSON válido")


def _no_trace(function, _name: str, _run_type: str):
    """Devuelve la función sin envolver (agente sin trazas).

    :param function: Función a envolver
    :type function: callable
    :return: La misma función
    :rtype: callable
    """
    return function


class Agent:
    """Agente que alterna entre el modelo y las herramientas hasta responder.

    No conoce el log ni el ``request_id``: avisa cada herramienta por
    ``on_tool_call`` y deja que quien lo llama decida qué registrar.

    :param model: Modelo que cumple la interfaz ``LanguageModel``, o un diccionario
        de modelos por nombre (el enrutador elige cuál en cada pregunta)
    :type model: app.llm.LanguageModel or dict[str, app.llm.LanguageModel]
    :param directory: Directorio de empleados de solo lectura
    :type directory: app.directory.EmployeeDirectory
    :param max_steps: Tope de vueltas del bucle
    :type max_steps: int
    :param tracer: Trazador opcional que envuelve corrida, modelo y herramientas
    :type tracer: app.tracing.Tracer or None
    """

    def __init__(self, model, directory, max_steps: int, tracer=None):
        wrap = tracer.wrap if tracer is not None else _no_trace
        if isinstance(model, dict):
            self._completions = {
                name: wrap(each.complete, "llm", "llm") for name, each in model.items()
            }
            self._default_complete = None
        else:
            self._completions = {}
            self._default_complete = wrap(model.complete, "llm", "llm")
        self._max_steps = max_steps
        self._tools = {
            name: (wrap(function, name, "tool"), expected)
            for name, function, expected in (
                ("get_employee", directory.get_employee, ("employee_id",)),
                (
                    "search_by_department",
                    directory.search_by_department,
                    ("department",),
                ),
                (
                    "get_vacation_balance",
                    directory.get_vacation_balance,
                    ("employee_id",),
                ),
                (
                    "department_summary",
                    directory.department_summary,
                    ("department",),
                ),
            )
        }
        self._traced_loop = wrap(self._loop, "agent_run", "chain")

    def _completion_for(self, model_name: str | None):
        """Devuelve la función ``complete`` del modelo pedido.

        :param model_name: Nombre del modelo; ``None`` usa el modelo único
        :type model_name: str or None
        :return: Función que recibe los mensajes y devuelve ``ModelReply``
        :rtype: callable
        :raises KeyError: Si el nombre no está entre los modelos del agente
        """
        if self._default_complete is not None:
            return self._default_complete
        if model_name is None:
            model_name = next(iter(self._completions))
        return self._completions[model_name]

    def _resolve_tool(self, request: dict) -> tuple:
        """Valida la herramienta pedida por el modelo y sus argumentos.

        :param request: Objeto con ``tool`` y ``args``
        :type request: dict
        :return: Nombre, función y argumentos de la herramienta
        :rtype: tuple[str, callable, dict]
        :raises ToolError: Si la herramienta o sus argumentos no sirven
        """
        name = request.get("tool")
        if not isinstance(name, str) or name not in self._tools:
            raise ToolError(f"herramienta desconocida: {name}")
        args = request.get("args", {})
        function, expected = self._tools[name]
        if not isinstance(args, dict) or set(args) != set(expected):
            raise ToolError(
                f"argumentos incorrectos para {name}; se esperaba "
                f"{', '.join(expected)}"
            )
        if not all(isinstance(args[key], str) for key in expected):
            raise ToolError(f"los argumentos de {name} deben ser texto")
        return name, function, dict(args)

    def run(
        self, question: str, history, on_tool_call=None, model_name=None
    ) -> AgentResult:
        """Responde una pregunta usando el modelo y las herramientas.

        :param question: Pregunta de la persona
        :type question: str
        :param history: Turnos previos con ``role`` y ``content``
        :type history: list[dict]
        :param on_tool_call: Se llama con ``(tool, args)`` antes de ejecutar cada
            herramienta válida
        :type on_tool_call: callable or None
        :param model_name: Modelo elegido por el enrutador; se usa en todas las
            vueltas
        :type model_name: str or None
        :return: Respuesta, pasos, herramientas, tokens y motivo de parada
        :rtype: AgentResult
        """
        return self._traced_loop(question, history, on_tool_call, model_name)

    def _loop(
        self, question: str, history, on_tool_call, model_name=None
    ) -> AgentResult:
        """Bucle de modelo y herramientas con tope de vueltas.

        :param question: Pregunta de la persona
        :type question: str
        :param history: Turnos previos con ``role`` y ``content``
        :type history: list[dict]
        :param on_tool_call: Aviso de cada herramienta válida, o ``None``
        :type on_tool_call: callable or None
        :param model_name: Modelo elegido, o ``None`` para el modelo único
        :type model_name: str or None
        :return: Respuesta, pasos, herramientas, tokens y motivo de parada
        :rtype: AgentResult
        """
        complete = self._completion_for(model_name)
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(
            {"role": turn["role"], "content": turn["content"]}
            for turn in history or []
        )
        messages.append({"role": "user", "content": question})
        result = AgentResult(answer=FALLBACK_ANSWER, model=model_name)
        while result.steps < self._max_steps:
            result.steps += 1
            reply = complete(messages)
            result.add_reply(reply)
            try:
                data = extract_json_object(reply.text)
                if "answer" in data and "tool" not in data:
                    result.answer = str(data["answer"])
                    result.stopped = STOPPED_ANSWER
                    return result
                name, function, args = self._resolve_tool(data)
                if on_tool_call is not None:
                    on_tool_call(name, dict(args))
                output = function(**args)
                result.tools_used.append(name)
            except ToolError as error:
                output = f"Error: {error}"
            messages.append({"role": "assistant", "content": reply.text})
            messages.append({"role": "user", "content": TOOL_RESULT_PREFIX + output})
        result.answer = FALLBACK_ANSWER
        result.stopped = STOPPED_MAX_STEPS
        return result
