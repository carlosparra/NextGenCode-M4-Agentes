"""Detección y enmascarado de datos personales (PII) en texto libre.

Se aplica a la pregunta antes de mandarla al modelo, a los registros, a las
trazas de LangSmith y a la respuesta antes de devolverla. Los detectores son
expresiones regulares para identificadores mexicanos y de contacto.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# El orden importa: los patrones más específicos van primero para que un
# número de 18 dígitos (CLABE) no se reporte también como teléfono.
_DETECTORS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    (
        "curp",
        re.compile(
            r"\b[A-Z][AEIOUX][A-Z]{2}\d{6}[HM][A-Z]{5}[A-Z\d]\d\b", re.IGNORECASE
        ),
    ),
    ("rfc", re.compile(r"\b[A-Z&Ñ]{3,4}\d{6}[A-Z\d]{3}\b", re.IGNORECASE)),
    ("card", re.compile(r"\b(?:\d[ -]?){15}\d\b")),
    ("clabe", re.compile(r"\b\d{18}\b")),
    ("nss", re.compile(r"\b\d{11}\b")),
    ("phone", re.compile(r"(?<![\w-])(?:\+?52[ -]?)?(?:\d[ -]?){9}\d\b")),
)
_SALARY = re.compile(r"\$\s?\d{1,3}(?:[,.]?\d{3})+(?:\.\d{2})?")


@dataclass(frozen=True)
class PiiScan:
    """Resultado de revisar un texto.

    :param text: Texto con la PII enmascarada
    :type text: str
    :param kinds: Tipos de PII encontrados, sin repetir y en orden
    :type kinds: tuple[str, ...]
    """

    text: str
    kinds: tuple[str, ...] = ()

    @property
    def found(self) -> bool:
        """Indica si se encontró PII.

        :return: ``True`` si hubo al menos un hallazgo
        :rtype: bool
        """
        return bool(self.kinds)


def scan(text: str, include_amounts: bool = False) -> PiiScan:
    """Busca PII y la reemplaza por ``[TIPO]``.

    :param text: Texto a revisar
    :type text: str
    :param include_amounts: También enmascara montos en pesos (salarios)
    :type include_amounts: bool
    :return: Texto enmascarado y tipos encontrados
    :rtype: PiiScan
    """
    kinds: list[str] = []
    masked = text
    for kind, pattern in _DETECTORS:
        masked, count = pattern.subn(f"[{kind.upper()}]", masked)
        if count:
            kinds.append(kind)
    if include_amounts:
        masked, count = _SALARY.subn("[AMOUNT]", masked)
        if count:
            kinds.append("amount")
    return PiiScan(masked, tuple(kinds))


def mask(text: str) -> str:
    """Atajo: solo el texto enmascarado.

    :param text: Texto a revisar
    :type text: str
    :return: Texto sin PII
    :rtype: str
    """
    return scan(text).text


def mask_value(value):
    """Enmascara PII dentro de cualquier estructura JSON (para trazas).

    :param value: Texto, lista, diccionario u otro valor
    :type value: object
    :return: El mismo valor con los textos enmascarados
    :rtype: object
    """
    if isinstance(value, str):
        return mask(value)
    if isinstance(value, dict):
        return {key: mask_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [mask_value(item) for item in value]
    return value
