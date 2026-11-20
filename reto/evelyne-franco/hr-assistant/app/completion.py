"""Tipos comunes de los modelos del HR Assistant.

Define la interfaz ``Model``, la respuesta ``Completion`` y la
excepcion ``ModelUnavailable``. Viven aqui para que ``app.llm`` y
``app.gateway`` los compartan sin importarse entre si.

:seealso: ADR 0002 sobre la abstraccion del modelo y ADR 0007 sobre
    los tokens por llamada.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

# Prefijo con el que el agente devuelve al modelo el resultado de una
# herramienta; el modelo simulado y el prompt del gateway lo conocen.
TOOL_RESULT_PREFIX = "Resultado de la herramienta: "


class ModelUnavailable(Exception):
    """El modelo no pudo responder (red, status, cuerpo invalido).

    El mensaje nunca lleva secretos: solo describe el tipo de falla.
    La API la convierte en ``502 {"detail": "model unavailable"}``.
    """


@dataclass(frozen=True)
class Completion:
    """Respuesta de una llamada al modelo.

    Los tokens viajan con la respuesta y no en el modelo, para que
    peticiones concurrentes no mezclen sus conteos.

    :param text: Texto que devolvio el modelo.
    :type text: str
    :param input_tokens: Tokens de entrada de esta llamada.
    :type input_tokens: int
    :param output_tokens: Tokens de salida de esta llamada.
    :type output_tokens: int
    :param cached: ``True`` si la respuesta vino de la cache del
        gateway (no cuesta).
    :type cached: bool
    """

    text: str
    input_tokens: int
    output_tokens: int
    cached: bool = False


class Model(ABC):
    """Interfaz abstracta para proveedores de modelo.

    Todo proveedor tiene un ``name`` (con el que se busca su precio) e
    implementa ``complete(messages)``.
    """

    name: str = "fake"

    @abstractmethod
    def complete(self, messages: list[dict[str, str]]) -> Completion:
        """Genera una respuesta a partir de los mensajes.

        :param messages: Lista de mensajes con ``role`` y ``content``.
        :type messages: list[dict[str, str]]
        :return: Texto JSON con ``tool`` y ``args`` o ``answer``, mas
            los tokens de la llamada.
        :rtype: Completion
        :raises ModelUnavailable: Si el modelo no pudo responder.
        """
