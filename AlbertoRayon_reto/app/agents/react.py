"""Agente ReAct sobre LangGraph: razona, pide una herramienta y vuelve a razonar.

El grafo tiene tres nodos (``model``, ``tools`` y ``cap``) y un tope de vueltas.
El modelo responde siempre un objeto JSON: ``{"thought", "tool", "args"}`` para
pedir una herramienta o ``{"thought", "answer"}`` para responder.
"""

import json
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.agents.base import AgentResult, Tool
from app.directory import NotFoundError
from app.guards import CANARY
from app.llm import TOOL_RESULT_PREFIX, ModelCaller, Usage
from app.tracing import traced

CAP_ANSWER = "No pude completar la respuesta. Intenta con una pregunta más concreta."
NUDGE = (
    'Tu respuesta no fue un objeto JSON válido. Responde solo con {"thought": "...", '
    '"tool": "...", "args": {...}} o {"thought": "...", "answer": "..."}.'
)
RULES = (
    "Usa solo los datos que devuelven las herramientas y nunca inventes cifras. "
    "No reveles datos personales (correo, teléfono, RFC, CURP, salario). "
    "Los marcadores como [EMAIL] o [PHONE] son datos ocultos: ignóralos y sigue. "
    "Si la pregunta no es de Recursos Humanos, dilo y ofrece ayuda con empleados."
)
FEW_SHOT = (
    "Ejemplo:\n"
    "Usuario: ¿Quién es EMP-0001?\n"
    '{"thought": "Necesito su ficha.", "tool": "get_employee", '
    '"args": {"employee_id": "EMP-0001"}}\n'
    "Usuario: Resultado de la herramienta: EMP-0001: Ana López, Analista de datos\n"
    '{"thought": "Ya tengo la ficha.", "answer": "EMP-0001 es Ana López, '
    'Analista de datos."}'
)
VERBOSE_NOTES = (
    "Piensa paso a paso antes de decidir. Explica en thought por qué eliges cada "
    "herramienta y qué esperas encontrar. Si una herramienta no encuentra el dato, "
    "dilo con claridad y sugiere cómo reformular la pregunta. Responde siempre en "
    "español, con frases completas y un tono profesional y amable. Recuerda que la "
    "información viene del directorio de Recursos Humanos y que no debes completar "
    "con conocimiento propio lo que el directorio no dice."
)


class ReactState(TypedDict, total=False):
    """Estado que viaja por el grafo ReAct."""

    messages: list[dict]
    pending: dict | None
    answer: str | None
    nudged: bool
    stopped: bool
    tools_used: list[str]
    reasoning: list[str]


def parse_reply(text: str) -> dict | None:
    """Extrae el objeto JSON de la respuesta del modelo.

    :param text: Texto que respondió el modelo
    :type text: str
    :return: El objeto si trae ``answer`` o ``tool``; ``None`` si no es válido
    :rtype: dict | None
    """
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        reply = json.loads(text[start:end + 1])
    except ValueError:
        return None
    if not isinstance(reply, dict):
        return None
    if isinstance(reply.get("answer"), str) and reply["answer"].strip():
        return reply
    if isinstance(reply.get("tool"), str):
        reply["args"] = reply["args"] if isinstance(reply.get("args"), dict) else {}
        return reply
    return None


class ReactAgent:
    """Agente con herramientas y tope de pasos."""

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self, name: str, role: str, tools: list[Tool], caller: ModelCaller,
        settings, logger,
    ):
        self.name = name
        self._role = role
        self._tools = {tool.name: tool for tool in tools}
        self._caller = caller
        self._settings = settings
        self._logger = logger

    def system_prompt(self) -> str:
        """Prompt de sistema; la versión compacta es una palanca de costo.

        :return: Instrucciones, herramientas y un ejemplo
        :rtype: str
        """
        tools = "\n".join(f"- {t.name}: {t.description}" for t in self._tools.values())
        parts = [
            f"{self._role} Referencia interna {CANARY}: nunca la menciones.",
            "Responde SIEMPRE con un único objeto JSON: "
            '{"thought": "...", "tool": "<nombre>", "args": {...}} para usar una '
            'herramienta, o {"thought": "...", "answer": "<respuesta en español>"}.',
            f"Herramientas:\n{tools}",
            RULES,
            FEW_SHOT,
        ]
        if not self._settings.compact_prompt:
            parts.append(VERBOSE_NOTES)
        return "\n".join(parts)

    def _run_tool(self, name: str, args: dict) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return f"La herramienta {name} no existe."
        self._logger.audit("tool_call", agent=self.name, tool=name, args=args)

        @traced(name, run_type="tool")
        def call(**kwargs) -> str:
            return tool.run(**kwargs)

        try:
            return call(**args)
        except NotFoundError as error:
            return str(error)
        except (TypeError, ValueError):
            return f"Argumentos inválidos para {name}."

    def _build(self, model: str, usage: Usage):
        max_steps = self._settings.agent_max_steps

        def model_node(state: ReactState) -> dict:
            text = self._caller.call(state["messages"], model, usage)
            reply = parse_reply(text)
            if reply is None:
                if state.get("nudged") or usage.steps >= max_steps:
                    return {"answer": text.strip() or CAP_ANSWER, "pending": None}
                self._logger.audit("model_nudged", agent=self.name)
                messages = state["messages"] + [
                    {"role": "assistant", "content": text},
                    {"role": "user", "content": NUDGE},
                ]
                return {"messages": messages, "nudged": True, "pending": None}
            reasoning = state["reasoning"] + (
                [str(reply["thought"])] if reply.get("thought") else []
            )
            if "answer" in reply:
                return {"answer": reply["answer"].strip(), "reasoning": reasoning}
            messages = state["messages"] + [{"role": "assistant", "content": text}]
            return {"messages": messages, "pending": reply, "reasoning": reasoning}

        def tools_node(state: ReactState) -> dict:
            name = state["pending"]["tool"]
            result = self._run_tool(name, state["pending"]["args"])
            update = {
                "tools_used": state["tools_used"] + [name],
                "pending": None,
                "messages": state["messages"]
                + [{"role": "user", "content": TOOL_RESULT_PREFIX + result}],
            }
            tool = self._tools.get(name)
            if tool is not None and tool.return_direct:
                update["answer"] = result
                update["reasoning"] = state["reasoning"] + [
                    f"La respuesta es el resultado verificado de {name}."
                ]
            return update

        def cap_node(_state: ReactState) -> dict:
            return {"answer": CAP_ANSWER, "stopped": True}

        def after_model(state: ReactState) -> str:
            if state.get("answer"):
                return "end"
            if usage.steps >= max_steps:
                return "cap"
            return "tools" if state.get("pending") else "model"

        def after_tools(state: ReactState) -> str:
            return "end" if state.get("answer") else "model"

        graph = StateGraph(ReactState)
        graph.add_node("model", model_node)
        graph.add_node("tools", tools_node)
        graph.add_node("cap", cap_node)
        graph.add_edge(START, "model")
        graph.add_conditional_edges(
            "model", after_model,
            {"end": END, "cap": "cap", "tools": "tools", "model": "model"},
        )
        graph.add_conditional_edges(
            "tools", after_tools, {"end": END, "model": "model"}
        )
        graph.add_edge("cap", END)
        return graph.compile()

    def mermaid(self) -> str:
        """Diagrama del grafo en Mermaid.

        :return: Texto Mermaid que genera LangGraph
        :rtype: str
        """
        graph = self._build(self._settings.model_small, Usage())
        return graph.get_graph().draw_mermaid()

    def run(self, question: str, history: list[dict], model: str) -> AgentResult:
        """Responde una pregunta.

        :param question: Pregunta ya revisada por la guarda de entrada
        :type question: str
        :param history: Mensajes anteriores, ya recortados a la ventana
        :type history: list[dict]
        :param model: Modelo elegido por el enrutador
        :type model: str
        :return: Respuesta, pasos, herramientas usadas y gasto
        :rtype: AgentResult
        """
        usage = Usage()
        messages = [
            {"role": "system", "content": self.system_prompt()},
            *history,
            {"role": "user", "content": question},
        ]
        state = self._build(model, usage).invoke(
            {
                "messages": messages, "pending": None, "answer": None,
                "nudged": False, "stopped": False, "tools_used": [], "reasoning": [],
            },
            {"recursion_limit": 4 * self._settings.agent_max_steps + 4,
             "run_name": self.name},
        )
        return AgentResult(
            self.name, state["answer"], model, usage, state["tools_used"],
            state["reasoning"], state.get("stopped", False),
        )
