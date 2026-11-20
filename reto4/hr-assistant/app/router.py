"""Enrutador por regla: elige el modelo de cada pregunta (ADR 0007).

Es una regla en código, sin red ni otro modelo, para que sea explicable y gratis.
"""

import re
import unicodedata

KEYWORDS = ("compara", "resume", "explica", "por que", "analiza", "todos")
# Cada palabra clave cuenta solo al inicio de una palabra (ADR 0008); los
# espacios internos («por que») aceptan uno o más blancos.
KEYWORD_PATTERNS = tuple(
    (keyword, re.compile(r"\b" + r"\s+".join(map(re.escape, keyword.split()))))
    for keyword in KEYWORDS
)
ROUTE_DISABLED = "routing_disabled"
ROUTE_LONG = "long_question"
ROUTE_SIMPLE = "simple_question"
ROUTE_KEYWORD_PREFIX = "keyword:"


def normalize(text):
    """Pasa el texto a minúsculas y le quita los acentos.

    :param text: Texto original
    :type text: str
    :return: Texto sin acentos y en minúsculas
    :rtype: str
    """
    decomposed = unicodedata.normalize("NFKD", str(text).lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def choose_model(question, config):
    """Elige el modelo para una pregunta y explica el motivo.

    - ``MODEL_LARGE`` si el enrutamiento está apagado, si la pregunta pasa de
      ``ROUTER_MAX_CHARS`` caracteres o si una palabra empieza con una
      palabra clave (sin distinguir mayúsculas ni acentos).
    - ``MODEL_SMALL`` en cualquier otro caso.

    :param question: Pregunta de la persona
    :type question: str
    :param config: Configuración validada
    :type config: app.config.Config
    :return: Nombre del modelo y motivo (``route``)
    :rtype: tuple[str, str]
    """
    if not config.routing:
        return config.model_large, ROUTE_DISABLED
    if len(question) > config.router_max_chars:
        return config.model_large, ROUTE_LONG
    normalized = normalize(question)
    for keyword, pattern in KEYWORD_PATTERNS:
        if pattern.search(normalized):
            return config.model_large, ROUTE_KEYWORD_PREFIX + keyword
    return config.model_small, ROUTE_SIMPLE
