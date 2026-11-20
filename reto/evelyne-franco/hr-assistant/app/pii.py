"""Deteccion de informacion sensible (PII) con expresiones regulares.

``redact_pii`` es una funcion pura: recibe un texto y devuelve el texto
limpio y la lista de tipos encontrados. Cada coincidencia se cambia por
``[REDACTED:<kind>]``. No usa red, modelos, estado ni log, para que sea
rapida, determinista y facil de probar.

Los datos del directorio (nombre, ``EMP-0001``, departamento, puesto,
fechas ``YYYY-MM-DD`` y estado) son el negocio y nunca coinciden: los
detectores exigen formatos con largo exacto y limites de digito.

Los detectores corren del mas especifico al mas general: ``card``,
``curp``, ``rfc``, ``email`` y ``phone``. Asi un CURP no sale como RFC y
una tarjeta no sale como telefono.

:seealso: ``spec/05-security-hardening.md`` y ``output/plan.md``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

KIND_CARD = "card"
KIND_CURP = "curp"
KIND_RFC = "rfc"
KIND_EMAIL = "email"
KIND_PHONE = "phone"
MARK_TEMPLATE = "[REDACTED:{kind}]"

# Ni un digito pegado ni uno separado por un espacio o un guion.
_NO_DIGIT_BEFORE = r"(?<!\d)(?<!\d[ -])"
_NO_DIGIT_AFTER = r"(?![ -]?\d)"

# Tarjeta: 13 a 19 digitos, con espacios o guiones opcionales.
CARD_PATTERN = re.compile(
    _NO_DIGIT_BEFORE + r"\d(?:[ -]?\d){12,18}" + _NO_DIGIT_AFTER
)
# CURP: 4 letras, fecha (6 digitos), sexo, 5 letras, 1 alfanumerico y
# 1 digito: 18 caracteres.
CURP_PATTERN = re.compile(
    r"\b[A-Z]{4}\d{6}[HMX][A-Z]{5}[A-Z0-9]\d\b", re.IGNORECASE
)
# RFC de persona fisica: 4 letras, fecha (6 digitos) y homoclave de 3.
RFC_PATTERN = re.compile(r"\b[A-Z&Ñ]{4}\d{6}[A-Z0-9]{3}\b", re.IGNORECASE)
EMAIL_PATTERN = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"
)
# Telefono: 10 digitos, con o sin +52, espacios o guiones. Con prefijo,
# el limite va antes del ``+``; sin prefijo, antes del primer digito.
PHONE_PATTERN = re.compile(
    r"(?:(?<![\w+])\+52[ -]?|" + _NO_DIGIT_BEFORE + r"(?<!\+))"
    r"\d(?:[ -]?\d){9}"
    + _NO_DIGIT_AFTER
)


@dataclass(frozen=True)
class PiiResult:
    """Resultado de limpiar un texto.

    :param text: Texto con cada coincidencia reemplazada.
    :type text: str
    :param kinds: Tipos encontrados, sin repetir, en el orden de los
        detectores.
    :type kinds: list[str]
    """

    text: str
    kinds: list[str] = field(default_factory=list)


def luhn_valid(digits: str) -> bool:
    """Revisa un numero con el algoritmo de Luhn.

    :param digits: Solo digitos, sin separadores.
    :type digits: str
    :return: ``True`` si la suma de control es valida.
    :rtype: bool
    """
    total = 0
    for position, char in enumerate(reversed(digits)):
        value = int(char)
        if position % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _mark(kind: str) -> str:
    """Devuelve la marca que reemplaza a un tipo de PII.

    :param kind: Tipo de PII.
    :type kind: str
    :return: ``[REDACTED:<kind>]``.
    :rtype: str
    """
    return MARK_TEMPLATE.format(kind=kind)


def _redact_cards(text: str) -> tuple[str, bool]:
    """Oculta las tarjetas que pasan Luhn; las demas quedan igual.

    :param text: Texto a revisar.
    :type text: str
    :return: Texto limpio y si se oculto alguna tarjeta.
    :rtype: tuple[str, bool]
    """
    found = False

    def replace(match: re.Match[str]) -> str:
        nonlocal found
        digits = re.sub(r"\D", "", match.group())
        if not luhn_valid(digits):
            return match.group()
        found = True
        return _mark(KIND_CARD)

    return CARD_PATTERN.sub(replace, text), found


def _redact_pattern(
    text: str, pattern: re.Pattern[str], kind: str
) -> tuple[str, bool]:
    """Oculta cada coincidencia de un patron.

    :param text: Texto a revisar.
    :type text: str
    :param pattern: Expresion regular del tipo.
    :type pattern: re.Pattern[str]
    :param kind: Tipo de PII.
    :type kind: str
    :return: Texto limpio y si hubo alguna coincidencia.
    :rtype: tuple[str, bool]
    """
    cleaned, count = pattern.subn(_mark(kind), text)
    return cleaned, count > 0


def redact_pii(text: str) -> PiiResult:
    """Reemplaza la PII de un texto por ``[REDACTED:<kind>]``.

    Es idempotente: limpiar dos veces da el mismo texto y la segunda
    vez no reporta tipos.

    :param text: Texto original.
    :type text: str
    :return: Texto limpio y tipos encontrados, sin repetir.
    :rtype: PiiResult
    """
    kinds: list[str] = []
    cleaned, found = _redact_cards(text)
    if found:
        kinds.append(KIND_CARD)
    for pattern, kind in (
        (CURP_PATTERN, KIND_CURP),
        (RFC_PATTERN, KIND_RFC),
        (EMAIL_PATTERN, KIND_EMAIL),
        (PHONE_PATTERN, KIND_PHONE),
    ):
        cleaned, found = _redact_pattern(cleaned, pattern, kind)
        if found:
            kinds.append(kind)
    return PiiResult(text=cleaned, kinds=kinds)


def merge_kinds(*groups: list[str]) -> list[str]:
    """Une listas de tipos sin repetir y conservando el orden.

    :param groups: Listas de tipos.
    :type groups: list[str]
    :return: Tipos unicos en orden de aparicion.
    :rtype: list[str]
    """
    merged: list[str] = []
    for group in groups:
        for kind in group:
            if kind not in merged:
                merged.append(kind)
    return merged
