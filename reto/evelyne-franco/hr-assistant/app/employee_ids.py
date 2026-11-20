"""Ids de empleado: forma canonica y normalizacion (Adenda 1, A1).

El id canonico es ``EMP-dddd``. Ademas se reconocen, sin importar
mayusculas, «empleado 4», «empleado 004», «empleado #4», «emp 4»,
«emp-4» y «EMP4» (de 1 a 4 digitos, con ceros a la izquierda o sin
ellos), que se convierten en ``EMP-0004``. Un numero suelto sin la
palabra «empleado» o «emp» (por ejemplo «2021») no es un id.

``guard`` aplica ``normalize_employee_ids`` sobre la pregunta ya limpia
de PII, asi la forma canonica la ven el supervisor, el especialista y el
revisor.

:seealso: ``spec/06-multiagente.md``, Adenda 1.
"""

from __future__ import annotations

import re

EMPLOYEE_ID_PATTERN = re.compile(r"EMP-\d{4}")
ID_DIGITS = 4
# Palabra «empleado» o «emp» con limite de palabra, separador opcional
# (espacios, ``#`` o ``-``) y de 1 a 4 digitos sin otro digito pegado.
WRITTEN_ID_PATTERN = re.compile(
    r"\b(?:empleado|emp)[\s#-]*(\d{1,4})(?!\d)", re.IGNORECASE
)


def canonical_id(digits: str) -> str:
    """Arma el id canonico a partir de sus digitos.

    :param digits: De 1 a 4 digitos.
    :type digits: str
    :return: Id en forma ``EMP-dddd``.
    :rtype: str
    """
    return f"EMP-{int(digits):0{ID_DIGITS}d}"


def normalize_with_count(text: str) -> tuple[str, int]:
    """Normaliza los ids y cuenta cuantos cambiaron de forma.

    Un ``EMP-dddd`` ya canonico no cuenta como cambio.

    :param text: Texto ya limpio de PII.
    :type text: str
    :return: Texto normalizado y numero de ids reescritos.
    :rtype: tuple[str, int]
    """
    changed = 0

    def _replace(match: re.Match[str]) -> str:
        """Devuelve el id canonico de una coincidencia.

        :param match: Coincidencia de ``WRITTEN_ID_PATTERN``.
        :type match: re.Match[str]
        :return: Id ``EMP-dddd``.
        :rtype: str
        """
        nonlocal changed
        replacement = canonical_id(match.group(1))
        if match.group(0) != replacement:
            changed += 1
        return replacement

    return WRITTEN_ID_PATTERN.sub(_replace, text), changed


def normalize_employee_ids(text: str) -> str:
    """Convierte los ids escritos de otra forma en ``EMP-dddd``.

    Es idempotente: un texto ya normalizado queda igual.

    :param text: Texto ya limpio de PII.
    :type text: str
    :return: Texto con los ids en forma canonica.
    :rtype: str
    """
    return normalize_with_count(text)[0]
