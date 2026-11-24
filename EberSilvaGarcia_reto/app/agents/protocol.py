"""Protocolo entre los agentes y el modelo: un objeto JSON por respuesta.

- ``{"thought": "...", "tool": "<nombre>", "args": {...}}`` pide una herramienta.
- ``{"answer": "<respuesta en español>"}`` responde.

Los modelos pequeños a veces envuelven el JSON en texto o en bloques de código;
el analizador lo busca y, si no hay JSON válido, toma el texto como respuesta.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

TOOL_RESULT = "Resultado de la herramienta: "


@dataclass(frozen=True)
class Action:
    """Lo que decidió el modelo en un paso."""

    tool: str | None = None
    args: dict = field(default_factory=dict)
    answer: str = ""
    thought: str = ""
    parse_error: bool = False


def _first_json_object(text: str) -> dict | None:
    decoder = json.JSONDecoder()
    index = text.find("{")
    while index != -1:
        try:
            value, _ = decoder.raw_decode(text, index)
        except ValueError:
            index = text.find("{", index + 1)
            continue
        if isinstance(value, dict):
            return value
        index = text.find("{", index + 1)
    return None


def parse_action(text: str) -> Action:
    """Interpreta la respuesta del modelo.

    :param text: Texto crudo del modelo
    :type text: str
    :return: Acción: herramienta con argumentos, o respuesta final
    :rtype: Action
    """
    data = _first_json_object(text or "")
    if data is None:
        return Action(answer=(text or "").strip(), parse_error=True)
    thought = str(data.get("thought", "")).strip()
    tool = data.get("tool")
    if isinstance(tool, str) and tool.strip():
        args = data.get("args") if isinstance(data.get("args"), dict) else {}
        return Action(tool=tool.strip(), args=args, thought=thought)
    answer = data.get("answer")
    if isinstance(answer, str):
        return Action(answer=answer.strip(), thought=thought)
    return Action(answer=(text or "").strip(), thought=thought, parse_error=True)
