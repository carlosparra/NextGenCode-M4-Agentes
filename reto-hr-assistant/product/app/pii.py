"""Detector de datos personales (PII) con expresiones regulares y código.

Cada dato encontrado se reemplaza por un marcador (``[EMAIL]``, ``[CARD]``,
``[CURP]``, ``[RFC]`` o ``[PHONE]``). El módulo nunca guarda ni devuelve los
valores encontrados: solo el texto ya redactado y los tipos.

El orden de los detectores es fijo (correo, tarjeta, CURP, RFC, teléfono): una
CURP contiene la forma de un RFC y una tarjeta podría verse como teléfono, así
que el detector más específico va primero. Los números usan límites de dígito
con lookarounds para no tomar pedazos de otros números (fechas, ids
``EMP-0000``).
"""

import re
from collections.abc import Callable

# Un número no puede empezar ni terminar pegado a otro dígito, ni a un dígito
# separado por un espacio o guion: así dos fechas seguidas no forman un teléfono.
_NUMBER_START = r"(?<!\d)(?<!\d[ -])"
_NUMBER_END = r"(?!\d)(?![ -]\d)"

EMAIL_PATTERN = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"
)
CARD_PATTERN = re.compile(_NUMBER_START + r"\d(?:[ -]?\d){12,18}" + _NUMBER_END)
CURP_PATTERN = re.compile(
    r"\b[A-Z][AEIOUX][A-Z]{2}\d{6}[HM][A-Z]{5}[A-Z\d]\d\b", re.IGNORECASE
)
RFC_PATTERN = re.compile(r"\b[A-ZÑ&]{3,4}\d{6}[A-Z\d]{3}\b", re.IGNORECASE)
# Diez dígitos, con espacios o guiones opcionales y, si viene, la lada +52.
PHONE_PATTERN = re.compile(
    r"(?:(?<![\w+])\+52[ -]?|" + _NUMBER_START + r")"
    r"\d(?:[ -]?\d){9}" + _NUMBER_END
)
LUHN_DOUBLE_LIMIT = 9


def passes_luhn(digits: str) -> bool:
    """Indica si una cadena de dígitos pasa el algoritmo de Luhn.

    :param digits: Solo dígitos, sin espacios ni guiones
    :type digits: str
    :return: ``True`` si la suma de control es múltiplo de 10
    :rtype: bool
    """
    total = 0
    for position, char in enumerate(reversed(digits)):
        value = int(char)
        if position % 2 == 1:
            value *= 2
            if value > LUHN_DOUBLE_LIMIT:
                value -= LUHN_DOUBLE_LIMIT
        total += value
    return total % 10 == 0


def _is_card(candidate: str) -> bool:
    """Indica si un número de 13 a 19 dígitos es una tarjeta válida por Luhn.

    :param candidate: Texto encontrado, con espacios o guiones opcionales
    :type candidate: str
    :return: ``True`` si sus dígitos pasan Luhn
    :rtype: bool
    """
    return passes_luhn(re.sub(r"\D", "", candidate))


def _always(_candidate: str) -> bool:
    """Acepta cualquier coincidencia del patrón.

    :param _candidate: Texto encontrado (no se usa)
    :type _candidate: str
    :return: Siempre ``True``
    :rtype: bool
    """
    return True


# Tipo, patrón y validación extra, en el orden en que se aplican.
DETECTORS: tuple[tuple[str, re.Pattern, Callable[[str], bool]], ...] = (
    ("EMAIL", EMAIL_PATTERN, _always),
    ("CARD", CARD_PATTERN, _is_card),
    ("CURP", CURP_PATTERN, _always),
    ("RFC", RFC_PATTERN, _always),
    ("PHONE", PHONE_PATTERN, _always),
)
PII_TYPES = tuple(name for name, _, _ in DETECTORS)


def marker(pii_type: str) -> str:
    """Devuelve el marcador que reemplaza a un tipo de PII.

    :param pii_type: Tipo (``EMAIL``, ``CARD``, ``CURP``, ``RFC`` o ``PHONE``)
    :type pii_type: str
    :return: Marcador entre corchetes, por ejemplo ``[EMAIL]``
    :rtype: str
    """
    return f"[{pii_type}]"


def _replace_type(
    text: str, pii_type: str, pattern: re.Pattern, accepts: Callable[[str], bool]
) -> tuple[str, bool]:
    """Reemplaza las coincidencias aceptadas de un tipo por su marcador.

    :param text: Texto a revisar
    :type text: str
    :param pii_type: Tipo de PII
    :type pii_type: str
    :param pattern: Patrón del tipo
    :type pattern: re.Pattern
    :param accepts: Validación extra de cada coincidencia (por ejemplo, Luhn)
    :type accepts: callable
    :return: Texto con marcadores y si hubo al menos un reemplazo
    :rtype: tuple[str, bool]
    """
    hits = []

    def replace(match: re.Match) -> str:
        if not accepts(match.group(0)):
            return match.group(0)
        hits.append(True)
        return marker(pii_type)

    return pattern.sub(replace, text), bool(hits)


def redact(text: str) -> tuple[str, list[str]]:
    """Reemplaza cada dato personal del texto por su marcador.

    :param text: Texto a revisar
    :type text: str
    :return: Texto redactado y tipos encontrados, sin duplicados y en el orden de
        los detectores; nunca los valores
    :rtype: tuple[str, list[str]]
    """
    found: list[str] = []
    for pii_type, pattern, accepts in DETECTORS:
        text, hit = _replace_type(text, pii_type, pattern, accepts)
        if hit:
            found.append(pii_type)
    return text, found
