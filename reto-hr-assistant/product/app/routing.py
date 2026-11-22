"""Enrutador de costo: una regla en código elige el modelo de cada pregunta."""

import re
import unicodedata
from dataclasses import dataclass

# Palabras que piden razonar o abarcar mucho: van al modelo capaz.
LARGE_MODEL_KEYWORDS = ("compara", "resume", "explica", "por qué", "analiza", "todos")
REASON_DISABLED = "routing_disabled"
REASON_LONG = "long_question"
REASON_DEFAULT = "default_small"
KEYWORD_REASON_PREFIX = "keyword:"


@dataclass(frozen=True)
class Route:
    """Modelo elegido para una pregunta y el motivo.

    :param model: Nombre del modelo
    :type model: str
    :param reason: Motivo (``routing_disabled``, ``long_question``,
        ``keyword:<palabra>`` o ``default_small``)
    :type reason: str
    """

    model: str
    reason: str


def normalize(text: str) -> str:
    """Pasa a minúsculas y quita los acentos para comparar palabras.

    :param text: Texto original
    :type text: str
    :return: Texto sin acentos y en minúsculas
    :rtype: str
    """
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _keyword_pattern(keyword: str) -> re.Pattern:
    """Arma el patrón de una palabra clave como palabra completa.

    Los límites son lookarounds de carácter de palabra, así que «resume» no
    coincide dentro de «resumen» y «por qué» sí coincide en «¿Por que...?».

    :param keyword: Palabra clave original
    :type keyword: str
    :return: Patrón sobre el texto normalizado
    :rtype: re.Pattern
    """
    return re.compile(r"(?<!\w)" + re.escape(normalize(keyword)) + r"(?!\w)")


KEYWORD_PATTERNS = tuple(
    (keyword, _keyword_pattern(keyword)) for keyword in LARGE_MODEL_KEYWORDS
)


def _find_keyword(question: str) -> str | None:
    """Busca la primera palabra clave que aparece completa en la pregunta.

    :param question: Pregunta de la persona
    :type question: str
    :return: Palabra clave encontrada o ``None``
    :rtype: str or None
    """
    normalized = normalize(question)
    for keyword, pattern in KEYWORD_PATTERNS:
        if pattern.search(normalized):
            return keyword
    return None


def choose_model(question: str, settings) -> Route:
    """Elige el modelo para una pregunta.

    El modelo capaz se usa si el enrutamiento está apagado, si la pregunta pasa de
    ``ROUTER_MAX_CHARS`` caracteres o si contiene una palabra clave completa; si
    no, el modelo barato.

    :param question: Pregunta de la persona
    :type question: str
    :param settings: Configuración validada
    :type settings: app.config.Settings
    :return: Modelo elegido y motivo
    :rtype: Route
    """
    costs = settings.costs
    if not costs.routing:
        return Route(costs.model_large, REASON_DISABLED)
    if len(question) > costs.router_max_chars:
        return Route(costs.model_large, REASON_LONG)
    keyword = _find_keyword(question)
    if keyword is not None:
        return Route(costs.model_large, KEYWORD_REASON_PREFIX + keyword)
    return Route(costs.model_small, REASON_DEFAULT)


def window_history(history: list, window: int) -> list:
    """Devuelve solo los últimos ``window`` mensajes del historial.

    Con ``window`` igual a 0 no se manda ninguno (``history[-0:]`` devolvería todo).

    :param history: Turnos previos, del más viejo al más nuevo
    :type history: list[dict]
    :param window: Mensajes que se conservan
    :type window: int
    :return: Los últimos mensajes del historial
    :rtype: list[dict]
    """
    if window <= 0:
        return []
    return list(history[-window:])
