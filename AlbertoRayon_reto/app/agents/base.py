"""Piezas comunes de los agentes."""

from dataclasses import dataclass, field
from typing import Callable

from app.llm import Usage


@dataclass(frozen=True)
class Tool:
    """Herramienta de solo lectura que un agente puede pedir."""

    name: str
    description: str
    run: Callable[..., str]
    return_direct: bool = False


@dataclass
class AgentResult:
    """Resultado de una corrida de agente."""

    agent: str
    answer: str
    model: str
    usage: Usage
    tools_used: list[str] = field(default_factory=list)
    reasoning: list[str] = field(default_factory=list)
    stopped: bool = False
