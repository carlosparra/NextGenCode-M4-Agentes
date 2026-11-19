"""Tipos comunes a todos los modelos: la respuesta y el protocolo ``LLM``.

Vive aparte para que el modelo simulado y el de gateway lo compartan sin
importarse entre si.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Completion:
    """Respuesta de un modelo.

    :param text: Texto devuelto por el modelo
    :type text: str
    :param input_tokens: Tokens de entrada consumidos
    :type input_tokens: int
    :param output_tokens: Tokens de salida generados
    :type output_tokens: int
    :param model: Nombre del modelo que respondio (vacio si no se conoce)
    :type model: str
    :param cached: Si la respuesta vino de la cache del gateway (no cuesta)
    :type cached: bool
    """

    text: str
    input_tokens: int
    output_tokens: int
    model: str = ""
    cached: bool = False


class LLM(Protocol):  # pylint: disable=too-few-public-methods
    """Protocolo que debe cumplir cualquier modelo usado por el agente."""

    def complete(self, messages: list) -> Completion:
        """Genera la siguiente respuesta para la conversacion.

        :param messages: Mensajes con ``role`` y ``content``
        :type messages: list[dict]
        :return: Texto del modelo y tokens consumidos
        :rtype: Completion
        """
