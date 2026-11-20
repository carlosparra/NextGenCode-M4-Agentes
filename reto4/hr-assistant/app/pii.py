"""Detección y enmascarado de PII en preguntas y respuestas.

Antes de llamar al modelo se enmascara la pregunta y el historial, y antes de
responder se enmascara la respuesta. Así ningún dato sensible que escriba el
usuario llega al proveedor ni a las trazas, y el modelo no puede devolver uno.
Solo se registra qué tipos se encontraron y cuántos, nunca el valor.
"""

import re
from collections import Counter

# El orden importa: CURP antes que RFC (comparten el inicio) y tarjeta antes
# que teléfono y NSS (una tarjeta contiene secuencias de esos largos).
PII_PATTERNS = (
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    ("curp", re.compile(r"\b[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\d\b", re.IGNORECASE)),
    ("rfc", re.compile(r"\b[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}\b", re.IGNORECASE)),
    ("card", re.compile(r"\b(?:\d[ -]?){12,15}\d\b")),
    ("nss", re.compile(r"\b\d{11}\b")),
    ("phone", re.compile(r"(?<![\w-])(?:\+?52[ -]?)?(?:\d[ -]?){9}\d\b")),
)
MASK_TEMPLATE = "[{kind} oculto]"


def mask_pii(text):
    """Reemplaza la PII del texto por una marca con su tipo.

    :param text: Texto a revisar
    :type text: str
    :return: El texto enmascarado y cuántas veces apareció cada tipo
    :rtype: tuple[str, collections.Counter]
    """
    found = Counter()
    for kind, pattern in PII_PATTERNS:
        text, count = pattern.subn(MASK_TEMPLATE.format(kind=kind), text)
        if count:
            found[kind] += count
    return text, found
