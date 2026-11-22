"""Filtro de la respuesta del modelo antes de que llegue al cliente.

El orden es fijo: primero se quitan las etiquetas HTML (una etiqueta puede partir
un correo), después se redacta la PII y al final se recorta (recortar antes
dejaría medio dato sin detectar). Si queda vacía se usa un texto de respaldo.
"""

import re
from collections.abc import Callable

FALLBACK_ANSWER = "No tengo una respuesta para eso."
# Una etiqueta completa o una etiqueta abierta que llega al final del texto. Debe
# empezar con letra, ``/`` o ``!`` para no borrar comparaciones como «5 < 10».
HTML_TAG_PATTERN = re.compile(r"</?[A-Za-z!][^<>]*(?:>|$)")

Redactor = Callable[[str], tuple[str, list[str]]]


def strip_html(text: str) -> str:
    """Quita las etiquetas HTML del texto, sin interpretar su contenido.

    :param text: Texto del modelo
    :type text: str
    :return: Texto sin etiquetas
    :rtype: str
    """
    return HTML_TAG_PATTERN.sub("", text)


def clean_answer(
    text: str, max_chars: int, redactor: Redactor | None = None
) -> tuple[str, list[str]]:
    """Limpia la respuesta: quita HTML, redacta PII, recorta y aplica el respaldo.

    :param text: Respuesta del modelo
    :type text: str
    :param max_chars: Largo máximo de la respuesta (``MAX_ANSWER_CHARS``)
    :type max_chars: int
    :param redactor: Función que redacta PII (``app.pii.redact``); ``None`` no
        redacta, pero el HTML y el recorte se aplican igual
    :type redactor: callable or None
    :return: Respuesta limpia y tipos de PII encontrados, nunca los valores
    :rtype: tuple[str, list[str]]
    """
    cleaned = strip_html(text)
    types: list[str] = []
    if redactor is not None:
        cleaned, types = redactor(cleaned)
    cleaned = cleaned[:max_chars].strip()
    return (cleaned or FALLBACK_ANSWER), types
