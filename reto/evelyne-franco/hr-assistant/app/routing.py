"""Palancas de costo que se deciden antes de llamar al modelo.

Palanca 1: ``route_question`` elige el modelo con una regla en codigo
(no con otro modelo). Palanca 2: ``window_history`` deja solo los
ultimos mensajes del historial.

:seealso: ``spec/03-costs.md`` puntos 2 y 3, y ADR 0008.
"""

from __future__ import annotations

from typing import NamedTuple

from app.config import Settings
from app.text import fold_text

REASON_ROUTING_DISABLED = "routing_disabled"
REASON_LONG_QUESTION = "long_question"
REASON_KEYWORD = "keyword"
REASON_SIMPLE_QUESTION = "simple_question"
# Palabras que piden razonar; se comparan sin acentos ni mayusculas.
LARGE_MODEL_KEYWORDS = tuple(
    fold_text(word)
    for word in ("compara", "resume", "explica", "por qué", "analiza", "todos")
)


class Route(NamedTuple):
    """Modelo elegido para una pregunta y el motivo.

    :param model: Nombre del modelo (``MODEL_SMALL`` o ``MODEL_LARGE``).
    :type model: str
    :param reason: ``routing_disabled``, ``long_question``,
        ``keyword`` o ``simple_question``.
    :type reason: str
    """

    model: str
    reason: str


def route_question(question: str, settings: Settings) -> Route:
    """Elige el modelo para una pregunta con una regla determinista.

    ``MODEL_LARGE`` si el enrutamiento esta apagado, si la pregunta
    pasa de ``ROUTER_MAX_CHARS`` o si contiene una palabra clave; si
    no, ``MODEL_SMALL``.

    :param question: Pregunta ya validada.
    :type question: str
    :param settings: Configuracion con los modelos y el limite.
    :type settings: app.config.Settings
    :return: Modelo y motivo.
    :rtype: Route
    """
    if not settings.routing:
        return Route(settings.model_large, REASON_ROUTING_DISABLED)
    if len(question) > settings.router_max_chars:
        return Route(settings.model_large, REASON_LONG_QUESTION)
    folded = fold_text(question)
    if any(keyword in folded for keyword in LARGE_MODEL_KEYWORDS):
        return Route(settings.model_large, REASON_KEYWORD)
    return Route(settings.model_small, REASON_SIMPLE_QUESTION)


def window_history(
    history: list[dict[str, str]], size: int
) -> list[dict[str, str]]:
    """Deja solo los ultimos ``size`` mensajes del historial.

    :param history: Historial que mando el cliente.
    :type history: list[dict[str, str]]
    :param size: Mensajes que se conservan; 0 no deja ninguno.
    :type size: int
    :return: Los ultimos ``size`` mensajes, en orden.
    :rtype: list[dict[str, str]]
    """
    if size <= 0:
        return []
    return list(history[-size:])
