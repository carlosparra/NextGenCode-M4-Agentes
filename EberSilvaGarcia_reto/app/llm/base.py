"""Interfaz común de los modelos de lenguaje.

Los agentes no saben qué proveedor hay detrás: solo llaman ``complete``. Así se
cambia el modelo simulado por el real (o por otro proveedor) sin tocarlos.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Completion:
    """Respuesta de una llamada al modelo.

    :param text: Texto generado
    :type text: str
    :param input_tokens: Tokens de entrada
    :type input_tokens: int
    :param output_tokens: Tokens de salida
    :type output_tokens: int
    :param model: Modelo que respondió
    :type model: str
    :param cached: ``True`` si la respondió la caché del gateway (no cuesta)
    :type cached: bool
    """

    text: str
    input_tokens: int
    output_tokens: int
    model: str
    cached: bool = False


class ModelUnavailable(RuntimeError):
    """El proveedor del modelo no respondió después de los reintentos."""


class ChatModel(Protocol):
    """Lo que el producto necesita de un proveedor de modelos."""

    async def complete(
        self, messages: list[dict], model: str, max_tokens: int
    ) -> Completion:
        """Genera la siguiente respuesta de la conversación."""
