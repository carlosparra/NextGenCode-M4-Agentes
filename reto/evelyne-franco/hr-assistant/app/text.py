"""Utilidades de texto compartidas por el modelo y el directorio."""

from __future__ import annotations

import unicodedata


def fold_text(text: str) -> str:
    """Normaliza un texto para compararlo sin acentos ni mayusculas.

    :param text: Texto original.
    :type text: str
    :return: Texto en minusculas y sin marcas diacriticas.
    :rtype: str
    """
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.casefold()
