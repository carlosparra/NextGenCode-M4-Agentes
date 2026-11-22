"""Recorte puro del texto de la respuesta, sin red ni estado."""

ELLIPSIS = "…"


def limit_text(text, limit):
    """Recorta ``text`` a exactamente ``limit`` caracteres como máximo.

    Si el texto cabe, se devuelve igual. Si no, se conservan los primeros
    ``limit - 1`` caracteres y se agrega ``…`` (un solo carácter).

    :param text: Texto a limitar
    :type text: str
    :param limit: Largo máximo en caracteres; mínimo 1
    :type limit: int
    :return: El texto (recortado o no) y el largo original
    :rtype: tuple[str, int]
    :raises ValueError: Si ``limit`` es menor que 1
    """
    if limit < 1:
        raise ValueError(f"limit must be at least 1, got {limit}")
    original = len(text)
    if original <= limit:
        return text, original
    return text[: limit - 1] + ELLIPSIS, original
