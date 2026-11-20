"""Deteccion y enmascarado de datos sensibles (PII) con expresiones regulares.

Tipos que se detectan: ``email``, ``phone`` (de 7 a 10 digitos, con ``+52``
opcional, juntos o con separadores), ``curp``, ``rfc``, ``card`` (13 a 19
digitos que pasan Luhn) y ``nss`` (11 digitos). Las expresiones se compilan
una sola vez al importar.

Los solapes se resuelven por prioridad: correo, tarjeta, CURP, RFC, NSS y
telefono. Asi una CURP no cuenta ademas como RFC y una tarjeta no cuenta como
telefono ni NSS. ``EMP-0004`` y las fechas como ``2019-03-04`` no son PII.

Este modulo nunca escribe en el log: quien lo llama registra solo los tipos.
"""

import re
from dataclasses import dataclass

KIND_EMAIL = "email"
KIND_PHONE = "phone"
KIND_CURP = "curp"
KIND_RFC = "rfc"
KIND_CARD = "card"
KIND_NSS = "nss"

# Etiqueta que reemplaza cada dato al enmascarar.
LABELS = {
    KIND_EMAIL: "[EMAIL]",
    KIND_PHONE: "[TELEFONO]",
    KIND_CURP: "[CURP]",
    KIND_RFC: "[RFC]",
    KIND_CARD: "[TARJETA]",
    KIND_NSS: "[NSS]",
}

EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
# Tarjeta: 13 a 19 digitos con espacios o guiones opcionales; luego se exige Luhn.
CARD_PATTERN = re.compile(r"(?<![\w+])(?:\d[ -]?){12,18}\d(?!\w)")
# CURP: 4 letras, fecha, sexo, 5 letras (estado y consonantes), homoclave.
CURP_PATTERN = re.compile(
    r"(?<!\w)[A-Z][AEIOUX][A-Z]{2}\d{6}[HM][A-Z]{5}[A-Z0-9]\d(?!\w)", re.IGNORECASE
)
# RFC: 3 o 4 letras, fecha de 6 digitos y homoclave de 3.
RFC_PATTERN = re.compile(
    r"(?<![\w&])[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}(?!\w)", re.IGNORECASE
)
NSS_PATTERN = re.compile(r"(?<![\w+])\d{11}(?!\w)")
# Telefono: de 7 a 10 digitos con +52 opcional. Formas aceptadas: juntos
# (987654321), 10 digitos en grupos 2-4-4 o 3-3-4 con lada opcional entre
# parentesis y separadores de espacio, punto o guion ((55) 1234-5678), y 7 u 8
# digitos en grupos 3-4 o 4-4 (555-1234). El ultimo grupo siempre es de 4 digitos,
# asi una fecha como 2019-03-04 o un id como EMP-0004 no cuentan como telefono.
PHONE_PATTERN = re.compile(
    r"(?<![\w+])(?:\+52[ .-]?)?"
    r"(?:\d{7,10}"
    r"|(?:\(\d{2}\)|\d{2})[ .-]?\d{4}[ .-]?\d{4}"
    r"|(?:\(\d{3}\)|\d{3})[ .-]?\d{3}[ .-]?\d{4}"
    r"|\d{3,4}[ .-]\d{4})(?!\w)"
)

# Orden de prioridad para resolver solapes.
DETECTORS = (
    (KIND_EMAIL, EMAIL_PATTERN),
    (KIND_CARD, CARD_PATTERN),
    (KIND_CURP, CURP_PATTERN),
    (KIND_RFC, RFC_PATTERN),
    (KIND_NSS, NSS_PATTERN),
    (KIND_PHONE, PHONE_PATTERN),
)
CARD_MIN_DIGITS = 13
CARD_MAX_DIGITS = 19
LUHN_MODULUS = 10


@dataclass(frozen=True)
class _Finding:
    """Un dato encontrado: su tipo y su posicion, nunca su valor.

    :param kind: Tipo del dato (``email``, ``phone``, ...)
    :type kind: str
    :param start: Indice donde empieza
    :type start: int
    :param end: Indice donde termina (exclusivo)
    :type end: int
    """

    kind: str
    start: int
    end: int

    def overlaps(self, start: int, end: int) -> bool:
        """Indica si el tramo ``[start, end)`` se cruza con este hallazgo.

        :param start: Inicio del otro tramo
        :type start: int
        :param end: Fin del otro tramo (exclusivo)
        :type end: int
        :return: ``True`` si se cruzan
        :rtype: bool
        """
        return start < self.end and self.start < end


def passes_luhn(text: str) -> bool:
    """Comprueba el digito verificador de Luhn de un numero de tarjeta.

    :param text: Numero con o sin separadores
    :type text: str
    :return: ``True`` si tiene de 13 a 19 digitos y pasa Luhn
    :rtype: bool
    """
    digits = [int(char) for char in text if char.isdigit()]
    if not CARD_MIN_DIGITS <= len(digits) <= CARD_MAX_DIGITS:
        return False
    total = 0
    for position, digit in enumerate(reversed(digits)):
        if position % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % LUHN_MODULUS == 0


def _find(text: str) -> list:
    """Encuentra los datos sensibles de un texto sin solapes.

    :param text: Texto a revisar
    :type text: str
    :return: Hallazgos ordenados por posicion
    :rtype: list[_Finding]
    """
    findings = []
    for kind, pattern in DETECTORS:
        for match in pattern.finditer(text):
            if kind == KIND_CARD and not passes_luhn(match.group()):
                continue
            start, end = match.span()
            if any(found.overlaps(start, end) for found in findings):
                continue
            findings.append(_Finding(kind=kind, start=start, end=end))
    return sorted(findings, key=lambda found: found.start)


def detect(text: str) -> list:
    """Dice que tipos de datos sensibles tiene un texto.

    :param text: Texto a revisar
    :type text: str
    :return: Tipos encontrados, sin repetir y en orden alfabetico
    :rtype: list[str]
    """
    return sorted({found.kind for found in _find(text)})


def mask(text: str) -> str:
    """Reemplaza cada dato sensible por su etiqueta (``[EMAIL]``, ``[CURP]``...).

    :param text: Texto a enmascarar
    :type text: str
    :return: El texto con los datos reemplazados; igual si no habia ninguno
    :rtype: str
    """
    pieces = []
    cursor = 0
    for found in _find(text):
        pieces.append(text[cursor : found.start])
        pieces.append(LABELS[found.kind])
        cursor = found.end
    pieces.append(text[cursor:])
    return "".join(pieces)
