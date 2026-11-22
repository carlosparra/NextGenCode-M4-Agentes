"""Respuesta de un modelo de lenguaje, compartida por todos los proveedores."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelReply:
    """Respuesta de un modelo de lenguaje.

    :param text: Texto devuelto por el modelo
    :type text: str
    :param input_tokens: Tokens de entrada consumidos
    :type input_tokens: int
    :param output_tokens: Tokens de salida generados
    :type output_tokens: int
    :param cached: ``True`` si la respuesta salió de la caché del gateway (no cuesta)
    :type cached: bool
    """

    text: str
    input_tokens: int
    output_tokens: int
    cached: bool = False
