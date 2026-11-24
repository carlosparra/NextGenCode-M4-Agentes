"""Patrón ReAct como grafo de LangGraph, reutilizable por varios agentes.

Ciclo: el modelo piensa (``thought``) y elige una acción (``tool``), el código
ejecuta la herramienta y agrega la observación, y se repite hasta que el
modelo responde (``answer``) o se llega al tope de pasos.

::

    START -> reason --answer--> END
               |  ^
          tool |  | observación
               v  |
              act
               |
        tope   v
             give_up -> END
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ValidationError

from app.agents.protocol import TOOL_RESULT, parse_action
from app.agents.runtime import RunContext


@dataclass(frozen=True)
class Tool:
    """Una herramienta que el agente puede pedir.

    :param name: Nombre que usa el modelo
    :type name: str
    :param args_model: Esquema de argumentos (valida lo que pide el modelo)
    :type args_model: type[BaseModel]
    :param run: Función asíncrona ``(args, ctx) -> resultado``
    :type run: Callable
    :param return_direct: Si el resultado trae ``answer`` (ya verificado por
        código), se entrega tal cual y el agente termina sin otra llamada al
        modelo: evita que el modelo reescriba (y altere) números verificados
    :type return_direct: bool
    """

    name: str
    args_model: type[BaseModel]
    run: Callable[[BaseModel, RunContext], Awaitable[Any]]
    return_direct: bool = False


class ReactState(TypedDict, total=False):
    """Estado del grafo ReAct."""

    messages: list[dict]
    steps: int
    tools_used: list[str]
    thoughts: list[str]
    observations: dict[str, Any]
    pending: dict | None
    answer: str
    stopped: bool
    parse_errors: int
    nudged: bool
    retry: bool


def tool_message(name: str, result: Any, compact: bool) -> dict:
    """Mensaje con la observación de una herramienta.

    :param name: Herramienta
    :type name: str
    :param result: Resultado
    :type result: Any
    :param compact: JSON compacto (palanca de costo) o con sangría (línea base)
    :type compact: bool
    :return: Mensaje ``user`` que empieza con ``Resultado de la herramienta:``
    :rtype: dict
    """
    payload = {"tool": name, "result": result}
    text = (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if compact
        else json.dumps(payload, ensure_ascii=False, indent=2)
    )
    return {"role": "user", "content": TOOL_RESULT + text}


class ReactAgent:
    """Agente ReAct con tope de pasos sobre un grafo de LangGraph.

    :param name: Nombre del agente (aparece en logs y trazas)
    :type name: str
    :param tools: Herramientas disponibles
    :type tools: list[Tool]
    :param give_up: Respuesta al llegar al tope sin terminar
    :type give_up: str
    :param requires_tool: Regla de código que dice si la pregunta exige consultar
        una herramienta; si el modelo responde sin hacerlo, se le pide una vez que
        la use (autocorrección con tope)
    :type requires_tool: Callable[[list[dict]], bool] | None
    """

    NUDGE = (
        "Recordatorio: la pregunta menciona un empleado o un departamento. Usa una "
        "herramienta antes de responder y contesta solo con el JSON."
    )

    def __init__(
        self,
        name: str,
        tools: list[Tool],
        give_up: str,
        requires_tool: Callable[[list[dict]], bool] | None = None,
    ) -> None:
        self.name = name
        self._tools = {tool.name: tool for tool in tools}
        self._give_up = give_up
        self._requires_tool = requires_tool
        self.graph = self._build()

    def _build(self):
        graph = StateGraph(ReactState)
        graph.add_node("reason", self._reason)
        graph.add_node("act", self._act)
        graph.add_node("give_up", self._stop)
        graph.add_edge(START, "reason")
        graph.add_conditional_edges(
            "reason",
            self._after_reason,
            {"act": "act", "give_up": "give_up", "retry": "reason", "end": END},
        )
        graph.add_conditional_edges(
            "act", self._after_act, {"reason": "reason", "end": END}
        )
        graph.add_edge("give_up", END)
        return graph.compile(name=self.name)

    async def _reason(self, state: ReactState, config) -> ReactState:
        ctx: RunContext = config["configurable"]["ctx"]
        max_steps: int = config["configurable"]["max_steps"]
        text = await ctx.llm.chat(state["messages"], agent=self.name)
        action = parse_action(text)
        steps = state.get("steps", 0) + 1
        update: ReactState = {
            "retry": False,
            "steps": steps,
            "messages": state["messages"] + [{"role": "assistant", "content": text}],
            "parse_errors": state.get("parse_errors", 0) + action.parse_error,
            "thoughts": state.get("thoughts", [])
            + ([action.thought] if action.thought else []),
        }
        if action.tool is None and self._should_nudge(state, steps, max_steps):
            ctx.audit("agent_self_correction", agent=self.name, reason="tool_required")
            update["messages"] = update["messages"] + [
                {"role": "user", "content": self.NUDGE}
            ]
            update["nudged"] = True
            update["retry"] = True
            update["pending"] = None
        elif action.tool is None:
            update["answer"] = action.answer
            update["pending"] = None
        elif steps >= max_steps:
            update["pending"] = None
            update["stopped"] = True
        else:
            update["pending"] = {"tool": action.tool, "args": action.args}
        return update

    def _should_nudge(self, state: ReactState, steps: int, max_steps: int) -> bool:
        return (
            self._requires_tool is not None
            and not state.get("nudged")
            and not state.get("tools_used")
            and steps < max_steps
            and self._requires_tool(state["messages"])
        )

    @staticmethod
    def _after_reason(state: ReactState) -> str:
        if state.get("stopped"):
            return "give_up"
        if state.get("pending"):
            return "act"
        if state.get("retry"):
            return "retry"
        return "end"

    @staticmethod
    def _after_act(state: ReactState) -> str:
        return "end" if state.get("answer") else "reason"

    async def _act(self, state: ReactState, config) -> ReactState:
        ctx: RunContext = config["configurable"]["ctx"]
        pending = state["pending"] or {}
        name = pending.get("tool", "")
        result = await self._run_tool(name, pending.get("args") or {}, ctx)
        observations = dict(state.get("observations", {}))
        observations[name] = result
        update: ReactState = {
            "messages": state["messages"] + [tool_message(name, result, ctx.compact)],
            "tools_used": state.get("tools_used", []) + [name],
            "observations": observations,
            "pending": None,
        }
        tool = self._tools.get(name)
        if (
            tool
            and tool.return_direct
            and isinstance(result, dict)
            and "answer" in result
        ):
            update["answer"] = result["answer"]
        return update

    async def _run_tool(self, name: str, args: dict, ctx: RunContext) -> Any:
        tool = self._tools.get(name)
        if tool is None:
            ctx.audit(
                "tool_rejected", agent=self.name, tool=name, reason="unknown_tool"
            )
            return f"La herramienta {name} no existe. Usa: {', '.join(self._tools)}."
        try:
            parsed = tool.args_model.model_validate(args)
        except ValidationError as exc:
            fields = sorted({".".join(map(str, e["loc"])) for e in exc.errors()})
            ctx.audit(
                "tool_rejected",
                agent=self.name,
                tool=name,
                reason="invalid_args",
                fields=fields,
            )
            return f"Argumentos inválidos para {name}: {', '.join(fields)}."
        ctx.audit("tool_call", agent=self.name, tool=name, args=parsed.model_dump())
        return await tool.run(parsed, ctx)

    def _stop(self, state: ReactState) -> ReactState:
        del state
        return {"answer": self._give_up, "stopped": True}

    async def run(
        self, messages: list[dict], ctx: RunContext, max_steps: int
    ) -> ReactState:
        """Corre el agente hasta que responde o llega al tope.

        :param messages: Mensajes iniciales (sistema, historial y pregunta)
        :type messages: list[dict]
        :param ctx: Contexto de la corrida
        :type ctx: RunContext
        :param max_steps: Tope de llamadas al modelo
        :type max_steps: int
        :return: Estado final del grafo
        :rtype: ReactState
        """
        initial: ReactState = {
            "messages": messages,
            "steps": 0,
            "tools_used": [],
            "thoughts": [],
            "observations": {},
            "pending": None,
            "answer": "",
            "stopped": False,
            "parse_errors": 0,
            "nudged": False,
            "retry": False,
        }
        config = {
            "configurable": {"ctx": ctx, "max_steps": max_steps},
            "recursion_limit": 2 * max_steps + 5,
            "run_name": self.name,
            "metadata": {"request_id": ctx.request_id, "agent": self.name},
        }
        return await self.graph.ainvoke(initial, config=config)
