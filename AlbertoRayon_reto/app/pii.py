"""Detección y enmascarado de datos personales en textos."""

import re

# El orden importa: lo más específico primero, para que un RFC no se lea como teléfono
PATTERNS = (
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("CURP", re.compile(r"\b[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\d\b", re.I)),
    ("RFC", re.compile(r"\b[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}\b", re.I)),
    ("CARD", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("CLABE", re.compile(r"\b\d{18}\b")),
    ("NSS", re.compile(r"\b\d{11}\b")),
    ("PHONE", re.compile(r"(?<![\w-])(?:\+?52[ -]?)?(?:\d[ -]?){9}\d\b")),
)


def _luhn(digits: str) -> bool:
    total = 0
    for position, char in enumerate(reversed(digits)):
        value = int(char)
        if position % 2 == 1:
            value = value * 2 - 9 if value > 4 else value * 2
        total += value
    return total % 10 == 0


def _is_match(kind: str, text: str) -> bool:
    digits = re.sub(r"\D", "", text)
    if kind == "CARD":
        return len(digits) != 18 and _luhn(digits)
    return True


def mask(text: str) -> tuple[str, list[str]]:
    """Reemplaza cada dato personal por un marcador como ``[EMAIL]``.

    :param text: Texto original
    :type text: str
    :return: El texto enmascarado y los tipos encontrados, sin repetir
    :rtype: tuple[str, list[str]]
    """
    found: list[str] = []
    for kind, pattern in PATTERNS:

        def replace(match, kind=kind):
            if not _is_match(kind, match.group()):
                return match.group()
            if kind not in found:
                found.append(kind)
            return f"[{kind}]"

        text = pattern.sub(replace, text)
    return text, found


def scan(text: str) -> list[str]:
    """Tipos de datos personales que aparecen en un texto.

    :param text: Texto a revisar
    :type text: str
    :return: Tipos encontrados, por ejemplo ``["EMAIL", "PHONE"]``
    :rtype: list[str]
    """
    return mask(text)[1]
