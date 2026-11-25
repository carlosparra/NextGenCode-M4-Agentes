"""Precios, enrutamiento de modelos y contabilidad de uso por corrida.

:class:`LlmSession` es lo único que ven los agentes: elige el modelo, aplica
el tope de salida, cuenta tokens y costo, y deja cada llamada en LangSmith.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from langsmith import traceable

from app.clock import Clock
from app.domain.directory import normalize
from app.llm.base import ChatModel, Completion

COMPLEX_WORDS = ("compara", "resume", "explica", "por que", "analiza", "todos")


class PriceTable:
    """Precios en USD por millón de tokens.

    :param prices: ``{"modelo": {"input": 0.1, "output": 0.2}}``
    :type prices: dict
    """

    def __init__(self, prices: dict[str, dict[str, float]]) -> None:
        self._prices = prices

    @classmethod
    def from_file(cls, path: Path) -> "PriceTable":
        """Carga los precios de ``model_prices.json``.

        :param path: Ruta al archivo
        :type path: pathlib.Path
        :return: Tabla de precios
        :rtype: PriceTable
        """
        return cls(json.loads(path.read_text(encoding="utf-8"))["models"])

    def cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Costo de una llamada.

        :param model: Nombre del modelo
        :type model: str
        :param input_tokens: Tokens de entrada
        :type input_tokens: int
        :param output_tokens: Tokens de salida
        :type output_tokens: int
        :return: Costo en USD (0 si el modelo no tiene precio)
        :rtype: float
        """
        price = self._prices.get(model, {"input": 0.0, "output": 0.0})
        return (input_tokens * price["input"] + output_tokens * price["output"]) / 1e6


@dataclass(frozen=True)
class Route:
    """Modelo elegido y el motivo."""

    model: str
    reason: str


def choose_model(
    question: str, small: str, large: str, routing: bool, max_chars: int
) -> Route:
    """Enrutador por regla (no por otro modelo): barato salvo que haga falta.

    :param question: Pregunta de la persona
    :type question: str
    :param small: Modelo barato
    :type small: str
    :param large: Modelo capaz
    :type large: str
    :param routing: Si es ``False`` siempre usa el capaz (línea base)
    :type routing: bool
    :param max_chars: Preguntas más largas van al capaz
    :type max_chars: int
    :return: Modelo y motivo
    :rtype: Route
    """
    if not routing:
        return Route(large, "routing_disabled")
    if len(question) > max_chars:
        return Route(large, "long_question")
    flat = normalize(question)
    for word in COMPLEX_WORDS:
        if word in flat:
            return Route(large, f"keyword:{word}")
    return Route(small, "simple_question")


@dataclass
class Usage:
    """Lo que gastó una corrida completa (agente principal y subagentes)."""

    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    model_calls: int = 0
    cached_calls: int = 0
    models: list[str] = field(default_factory=list)

    def add(self, completion: Completion, cost: float) -> None:
        """Suma una llamada.

        :param completion: Respuesta del modelo
        :type completion: Completion
        :param cost: Costo calculado (0 si vino de caché)
        :type cost: float
        """
        self.model_calls += 1
        self.input_tokens += completion.input_tokens
        self.output_tokens += completion.output_tokens
        self.cost_usd += cost
        self.cached_calls += completion.cached
        if completion.model not in self.models:
            self.models.append(completion.model)


class LlmSession:
    """Acceso al modelo para una corrida, con contabilidad y trazas.

    :param model: Proveedor del modelo
    :type model: ChatModel
    :param prices: Tabla de precios
    :type prices: PriceTable
    :param route: Modelo elegido por el enrutador
    :type route: Route
    :param max_tokens: Tope de salida por llamada
    :type max_tokens: int
    :param clock: Reloj para medir latencia
    :type clock: Clock
    """

    # pylint: disable=too-many-arguments,too-many-positional-arguments

    def __init__(
        self,
        model: ChatModel,
        prices: PriceTable,
        route: Route,
        max_tokens: int,
        clock: Clock,
    ) -> None:
        self._model = model
        self._prices = prices
        self.route = route
        self._max_tokens = max_tokens
        self._clock = clock
        self.usage = Usage()
        self.model_latency_ms = 0.0

    async def chat(
        self, messages: list[dict], agent: str, model: str | None = None
    ) -> str:
        """Llama al modelo y registra el uso.

        :param messages: Conversación
        :type messages: list[dict]
        :param agent: Nombre del agente que llama (para la traza)
        :type agent: str
        :param model: Modelo explícito; por omisión, el del enrutador
        :type model: str | None
        :return: Texto de la respuesta
        :rtype: str
        """
        chosen = model or self.route.model
        completion = await self._call(messages, chosen, agent)
        cost = (
            0.0
            if completion.cached
            else self._prices.cost(
                completion.model, completion.input_tokens, completion.output_tokens
            )
        )
        self.usage.add(completion, cost)
        return completion.text

    async def _call(self, messages: list[dict], model: str, agent: str) -> Completion:
        start = self._clock.monotonic()
        completion = await _traced_completion(
            self._model, messages, model, self._max_tokens, agent
        )
        self.model_latency_ms += (self._clock.monotonic() - start) * 1000
        return completion


def _llm_outputs(completion: Completion) -> dict:
    """Formato que LangSmith entiende para mostrar tokens y costo del paso."""
    if not isinstance(completion, Completion):
        return {"output": None}
    return {
        "choices": [{"message": {"role": "assistant", "content": completion.text}}],
        "cached": completion.cached,
        "usage_metadata": {
            "input_tokens": completion.input_tokens,
            "output_tokens": completion.output_tokens,
            "total_tokens": completion.input_tokens + completion.output_tokens,
        },
    }


@traceable(
    run_type="llm",
    name="model.complete",
    process_outputs=_llm_outputs,
    metadata={"ls_provider": "cloudflare-workers-ai"},
)
async def _traced_completion(
    model: ChatModel, messages: list[dict], name: str, max_tokens: int, agent: str
) -> Completion:
    """Llamada al modelo como paso ``llm`` en LangSmith."""
    del agent  # solo queda como entrada visible en la traza
    return await model.complete(messages, name, max_tokens)
