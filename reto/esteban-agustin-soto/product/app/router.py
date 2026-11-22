"""Enrutador por reglas: elige el modelo barato o el capaz para cada pregunta."""

from app.directory import normalize

KEYWORDS = ("compara", "resume", "explica", "por qué", "analiza", "todos")


def choose_model(question, settings):
    """Elige el modelo de una pregunta con una regla en código.

    :param question: Pregunta de la persona
    :type question: str
    :param settings: Configuración con ``routing``, ``router_max_chars`` y los
        nombres de los modelos
    :type settings: app.config.Settings
    :return: El nombre del modelo y el motivo (``routing_off``, ``too_long``,
        ``keyword:<palabra>`` o ``simple``)
    :rtype: tuple
    """
    if not settings.routing:
        return settings.model_large, "routing_off"
    if len(question) > settings.router_max_chars:
        return settings.model_large, "too_long"
    normalized = normalize(question)
    for word in KEYWORDS:
        if normalize(word) in normalized:
            return settings.model_large, f"keyword:{word}"
    return settings.model_small, "simple"
