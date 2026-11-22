"""Agente con bucle acotado y dos herramientas de solo lectura."""

import json
import re
from dataclasses import dataclass, field
from typing import Optional

from app.config import DEFAULT_HISTORY_WINDOW
from app.llm import (
    TOOL_RESULT_INSTRUCTION,
    TOOL_RESULT_PREFIX,
    approximate_completion,
)

FAILURE_MESSAGE = (
    "No pude completar la respuesta. Intenta con una pregunta más concreta."
)
SYSTEM_PROMPT = (
    "Eres el HR Assistant. Responde siempre con un único objeto JSON.\n"
    "Herramientas disponibles:\n"
    "- get_employee: argumento employee_id (formato EMP-0004).\n"
    "- search_by_department: argumento department.\n"
    "Ejemplos:\n"
    '{"tool": "get_employee", "args": {"employee_id": "EMP-0004"}}\n'
    '{"tool": "search_by_department", "args": {"department": "Ventas"}}\n'
    '{"answer": "texto de la respuesta"}\n'
    "Para datos de empleados usa una herramienta. Cuando ya tengas la "
    "información, responde con answer. Si la herramienta dice que el "
    "empleado no existe, responde con answer diciéndolo."
)
_TOOL_NAMES = ("get_employee", "search_by_department")
_NOT_JSON = object()
_FENCE = re.compile(r"^```[A-Za-z]*\s*|\s*```$")


@dataclass
class AgentResult:
    """Resultado de una ejecución del agente.

    :param answer: Respuesta final
    :type answer: str
    :param steps: Vueltas del bucle usadas
    :type steps: int
    :param tools_used: Herramientas ejecutadas con éxito
    :type tools_used: list
    :param input_tokens: Tokens de entrada aproximados
    :type input_tokens: int
    :param output_tokens: Tokens de salida aproximados
    :type output_tokens: int
    :param calls: Una ``Completion`` por llamada al modelo (tokens y ``cached``)
    :type calls: list
    :param cost_usd: Costo en USD de la ejecución; ``None`` sin ``cost_fn``
    :type cost_usd: float or None
    """

    answer: str
    steps: int = 0
    tools_used: list = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    calls: list = field(default_factory=list)
    cost_usd: Optional[float] = None


def _legacy_generate(model):
    """Adapta un modelo que solo tiene ``complete`` a ``generate``.

    :param model: Objeto con ``complete(messages)``
    :return: Función ``messages -> Completion`` con tokens aproximados
    """

    def generate(messages):
        return approximate_completion(messages, model.complete(messages))

    return generate


def _first_object(text):
    """Toma el primer objeto JSON completo dentro de un texto.

    :param text: Texto con prosa y un objeto
    :type text: str
    :return: El primer ``dict`` decodificable o ``None``
    :rtype: dict or None
    """
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            found, _ = decoder.raw_decode(text, start)
        except ValueError:
            found = None
        if isinstance(found, dict):
            return found
        start = text.find("{", start + 1)
    return None


def _parse_text(text):
    """Intenta leer JSON directo, con valla de Markdown o dentro de prosa.

    :param text: Texto devuelto por el modelo
    :type text: str
    :return: El valor decodificado o ``_NOT_JSON``
    """
    try:
        return json.loads(text)
    except ValueError:
        pass
    unfenced = _FENCE.sub("", text.strip())
    try:
        return json.loads(unfenced)
    except ValueError:
        pass
    found = _first_object(text)
    return _NOT_JSON if found is None else found


def _normalize_output(raw):
    """Normaliza la salida del modelo a un objeto.

    :param raw: Texto o ``dict`` devuelto por el modelo
    :return: Tupla ``(objeto o None, motivo o None)``; el motivo es
        ``not_json`` o ``not_object`` cuando no hay objeto
    :rtype: tuple
    """
    value = _parse_text(raw) if isinstance(raw, str) else raw
    if value is _NOT_JSON:
        return None, "not_json"
    if not isinstance(value, dict):
        return None, "not_object"
    return value, None


def _raw_chars(raw):
    """Mide la salida del modelo sin exponer su contenido.

    :param raw: Salida original del modelo
    :return: Largo del texto o de su serialización JSON
    :rtype: int
    """
    if isinstance(raw, str):
        return len(raw)
    try:
        return len(json.dumps(raw, ensure_ascii=False))
    except (TypeError, ValueError):
        return 0


def _raw_text(raw):
    """Convierte la salida del modelo en texto para el historial.

    :param raw: Salida original del modelo (texto, dict u otro)
    :return: El texto tal cual o su serialización JSON
    :rtype: str
    """
    if isinstance(raw, str):
        return raw
    try:
        return json.dumps(raw, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(raw)


class Agent:  # pylint: disable=too-many-instance-attributes
    """Bucle en el que el modelo pide herramientas o responde.

    :param model: Objeto con ``generate(messages)`` o, si no, ``complete``
    :type model: object
    :param directory: Directorio de empleados
    :type directory: app.directory.EmployeeDirectory
    :param max_steps: Tope de vueltas del bucle
    :type max_steps: int
    :param logger: Objeto con ``log(event, **fields)``; opcional
    :type logger: object or None
    :param trace: Función ``(func, name) -> func`` que agrega trazas; opcional
    :type trace: collections.abc.Callable or None
    :param history_window: Mensajes de historial que se mandan al modelo
    :type history_window: int
    :param model_name: Nombre del modelo, para el evento ``agent_run``
    :type model_name: str or None
    :param route: Motivo del enrutador, para el evento ``agent_run``
    :type route: str or None
    :param cost_fn: Función ``calls -> USD``; si falta no hay costo
    :type cost_fn: collections.abc.Callable or None
    """

    def __init__(  # pylint: disable=too-many-arguments
        self, model, directory, max_steps, *, logger=None, trace=None,
        history_window=DEFAULT_HISTORY_WINDOW, model_name=None, route=None,
        cost_fn=None,
    ):
        self._cost_fn = cost_fn
        self._directory = directory
        self._max_steps = max_steps
        self._logger = logger
        self._history_window = history_window
        self._model_name = model_name
        self._route = route
        trace = trace or (lambda func, _name: func)
        generate = getattr(model, "generate", None) or _legacy_generate(model)
        self._generate = trace(generate, "llm_call")
        self._call_tool = trace(self._execute_tool, "tool")
        self._run = trace(self._run_loop, "agent_run")

    def _emit(self, event, **fields):
        """Emite un evento si hay logger.

        :param event: Nombre del evento
        :type event: str
        :param fields: Campos del evento
        """
        if self._logger is not None:
            self._logger.log(event, **fields)

    def run(self, question, history=None):
        """Responde una pregunta y emite ``audit`` y ``agent_run``.

        Con ``cost_fn`` calcula ``result.cost_usd`` una sola vez, antes de
        emitir ``agent_run``, y lo agrega al evento como ``cost_usd``.

        :param question: Pregunta de la persona
        :type question: str
        :param history: Mensajes previos con ``role`` y ``content``
        :type history: list or None
        :return: Respuesta, pasos, herramientas y tokens
        :rtype: AgentResult
        :raises ValueError: Si ``cost_fn`` no encuentra precio para el modelo;
            el error se propaga antes de emitir ``agent_run``
        """
        result, stopped = self._run(question, history)
        extra = {}
        if self._cost_fn is not None:
            result.cost_usd = self._cost_fn(result.calls)
            extra["cost_usd"] = result.cost_usd
        self._emit(
            "agent_run",
            question_chars=len(question),
            history_messages=len(history or []),
            steps=result.steps,
            tools=result.tools_used,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            stopped=stopped,
            model=self._model_name,
            route=self._route,
            cached_calls=sum(1 for call in result.calls if call.cached),
            **extra,
        )
        return result

    def _run_loop(self, question, history):
        """Ejecuta el bucle acotado.

        :param question: Pregunta de la persona
        :type question: str
        :param history: Mensajes previos o ``None``
        :type history: list or None
        :return: El resultado y el motivo de parada
        :rtype: tuple
        """
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        recent = list(history or [])[-self._history_window:]
        messages.extend(
            {"role": m["role"], "content": m["content"]} for m in recent
        )
        messages.append({"role": "user", "content": question})
        result = AgentResult(answer=FAILURE_MESSAGE)
        stopped = "max_steps"
        for _ in range(self._max_steps):
            result.steps += 1
            completion = self._generate(messages)
            result.calls.append(completion)
            result.input_tokens += completion.input_tokens
            result.output_tokens += completion.output_tokens
            answer = self._handle(completion.text, messages, result)
            if answer is not None:
                result.answer = answer
                stopped = "answer"
                break
        return result, stopped

    def _handle(self, raw, messages, result):
        """Interpreta la salida del modelo.

        Agrega a ``messages`` el resultado de la herramienta o el error.

        :param raw: Texto devuelto por el modelo
        :type raw: str
        :param messages: Conversación actual (se modifica)
        :type messages: list
        :param result: Resultado en construcción (se modifica)
        :type result: AgentResult
        :return: La respuesta final o ``None`` si hay que seguir
        :rtype: str or None
        """
        data, reason = _normalize_output(raw)
        if data is None:
            feedback = "Respuesta inválida: se esperaba un objeto JSON"
        elif isinstance(data.get("answer"), str) and "tool" not in data:
            return data["answer"]
        elif isinstance(data.get("tool"), str) and "answer" not in data:
            feedback = self._run_tool(data, result)
        else:
            reason = "bad_shape"
            feedback = "Respuesta inválida: use solo tool o answer"
        if reason is not None:
            self._emit(
                "invalid_model_output",
                reason=reason,
                raw_type=type(raw).__name__,
                raw_chars=_raw_chars(raw),
            )
        messages.append({"role": "assistant", "content": _raw_text(raw)})
        messages.append({"role": "user", "content": TOOL_RESULT_PREFIX + feedback})
        return None

    def _run_tool(self, data, result):
        """Ejecuta una herramienta pedida por el modelo.

        :param data: Objeto con ``tool`` y ``args``
        :type data: dict
        :param result: Resultado en construcción (se modifica)
        :type result: AgentResult
        :return: Texto con el resultado o con el error
        :rtype: str
        """
        name = data["tool"]
        args = data.get("args")
        if not isinstance(args, dict):
            args = {}
        if name == "get_employee" and "employee_id" in args:
            clean_args = {"employee_id": str(args["employee_id"])}
        elif name == "search_by_department" and "department" in args:
            clean_args = {"department": str(args["department"])}
        else:
            self._emit(
                "invalid_tool_call",
                tool=name if name in _TOOL_NAMES else "unknown",
                arg_keys=sorted(str(key) for key in args),
            )
            return f"Error: herramienta o argumentos inválidos ({name})"
        self._emit("audit", action="tool_call", tool=name, args=clean_args)
        output = self._call_tool(name, clean_args)
        result.tools_used.append(name)
        return json.dumps(output, ensure_ascii=False) + TOOL_RESULT_INSTRUCTION

    def _execute_tool(self, name, args):
        """Consulta el directorio con una herramienta ya validada.

        :param name: Nombre de la herramienta
        :type name: str
        :param args: Argumentos validados
        :type args: dict
        :return: Los datos encontrados o un mensaje de que no hay
        """
        if name == "get_employee":
            employee_id = args["employee_id"]
            found = self._directory.get_employee(employee_id)
            return found or f"No existe el empleado {employee_id}"
        department = args["department"]
        found = self._directory.search_by_department(department)
        return found or f"No hay empleados en {department}"
