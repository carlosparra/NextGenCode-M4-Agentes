"""Regla de enrutamiento por pregunta (palanca 1 de costo).

Una regla en codigo, no otro modelo, decide si la pregunta va al modelo barato
(``MODEL_SMALL``) o al capaz (``MODEL_LARGE``). Las palabras clave se comparan
sin mayusculas ni acentos.
"""

from dataclasses import dataclass

from app.config import Settings
from app.directory import normalize_text

REASON_ROUTING_DISABLED = "routing_disabled"
REASON_LONG_QUESTION = "long_question"
REASON_KEYWORD_PREFIX = "keyword:"
REASON_DEFAULT_SMALL = "default_small"

# Ya normalizadas: sin mayusculas ni acentos.
LARGE_MODEL_KEYWORDS = (
    "compara",
    "resume",
    "explica",
    "por que",
    "analiza",
    "todos",
)


@dataclass(frozen=True)
class Route:
    """Modelo elegido para una pregunta y el motivo.

    :param model: Nombre del modelo elegido
    :type model: str
    :param reason: Motivo: ``routing_disabled``, ``long_question``,
        ``keyword:<palabra>`` o ``default_small``
    :type reason: str
    """

    model: str
    reason: str


def route(question: str, settings: Settings) -> Route:
    """Elige el modelo para una pregunta.

    :param question: Pregunta de la persona
    :type question: str
    :param settings: Configuracion con los modelos y el umbral de largo
    :type settings: Settings
    :return: El modelo elegido y el motivo
    :rtype: Route
    """
    if not settings.routing:
        return Route(settings.model_large, REASON_ROUTING_DISABLED)
    if len(question) > settings.router_max_chars:
        return Route(settings.model_large, REASON_LONG_QUESTION)
    normalized = normalize_text(question)
    for keyword in LARGE_MODEL_KEYWORDS:
        if keyword in normalized:
            return Route(settings.model_large, REASON_KEYWORD_PREFIX + keyword)
    return Route(settings.model_small, REASON_DEFAULT_SMALL)
