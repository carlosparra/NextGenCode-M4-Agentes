"""Detección y enmascarado de CURP y correo (funciones puras, sin red)."""

import re

CURP_MARKER = "[CURP]"
EMAIL_MARKER = "[EMAIL]"
CURP_KIND = "curp"
EMAIL_KIND = "email"

_STATES = (
    "AS|BC|BS|CC|CL|CM|CS|CH|DF|DG|GT|GR|HG|JC|MC|MN|MS|NT|NL|OC|PL|QT|QR|"
    "SP|SL|SR|TC|TS|TL|VZ|YN|ZS|NE"
)
_CONSONANT = "[B-DF-HJ-NP-TV-Z]"

# Palabra completa de 18 caracteres: sin letra ni dígito pegado a los lados.
_CURP = re.compile(
    r"(?<![A-Za-z0-9])"
    r"[A-Z][AEIOUX][A-Z]{2}"
    r"[0-9]{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12][0-9]|3[01])"
    rf"[HMX](?:{_STATES}){_CONSONANT}{{3}}[A-Z0-9][0-9]"
    r"(?![A-Za-z0-9])",
    re.IGNORECASE | re.ASCII,
)

# El lookbehind evita empezar a medio usuario y mantiene el costo lineal.
_EMAIL = re.compile(
    r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+"
    r"@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}(?![A-Za-z])",
    re.ASCII,
)


def mask_counted(text):
    """Enmascara el texto y cuenta lo que reemplazó.

    :param text: Texto de entrada
    :type text: str
    :return: El texto enmascarado y ``{"curp": n, "email": n}``
    :rtype: tuple
    """
    masked, emails = _EMAIL.subn(EMAIL_MARKER, text)
    masked, curps = _CURP.subn(CURP_MARKER, masked)
    return masked, {CURP_KIND: curps, EMAIL_KIND: emails}


def empty_counts():
    """Da los conteos en cero.

    :return: Diccionario ``{"curp": 0, "email": 0}`` nuevo en cada llamada
    :rtype: dict
    """
    return {CURP_KIND: 0, EMAIL_KIND: 0}


def mask_text(text):
    """Reemplaza cada CURP por ``[CURP]`` y cada correo por ``[EMAIL]``.

    :param text: Texto de entrada
    :type text: str
    :return: El texto enmascarado; enmascararlo de nuevo no lo cambia
    :rtype: str
    """
    return mask_counted(text)[0]


def count_pii(text):
    """Cuenta las CURP y los correos que ``mask_text`` reemplazaría.

    :param text: Texto de entrada
    :type text: str
    :return: Diccionario ``{"curp": n, "email": n}``
    :rtype: dict
    """
    return mask_counted(text)[1]


def mask_deep(value):
    """Enmascara los strings dentro de dict, list y tuple.

    :param value: Valor de cualquier tipo; lo que no es str ni contenedor
        se devuelve igual
    :type value: object
    :return: Copia con los strings (y las claves str) enmascarados
    :rtype: object
    """
    if isinstance(value, str):
        return mask_text(value)
    if isinstance(value, dict):
        return {mask_deep(key): mask_deep(item) for key, item in value.items()}
    if isinstance(value, list):
        return [mask_deep(item) for item in value]
    if isinstance(value, tuple):
        return tuple(mask_deep(item) for item in value)
    return value
