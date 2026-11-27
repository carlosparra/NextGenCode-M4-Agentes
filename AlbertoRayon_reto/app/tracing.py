"""Trazas en LangSmith: opcionales y sin contenido cuando se ocultan.

LangGraph manda solo la traza de cada grafo cuando ``LANGSMITH_TRACING`` vale
``true``; ``traced`` agrega las llamadas al modelo y a las herramientas.
"""

import os

from langsmith import traceable

from app.config import Settings


def configure(settings: Settings) -> bool:
    """Enciende o apaga las trazas según la configuración.

    Sin clave no se intenta ninguna conexión, aunque ``LANGSMITH_TRACING`` valga
    ``true``.

    :param settings: Configuración del producto
    :type settings: Settings
    :return: ``True`` si las trazas quedaron encendidas
    :rtype: bool
    """
    enabled = settings.langsmith_tracing and bool(settings.langsmith_api_key)
    os.environ["LANGSMITH_TRACING"] = "true" if enabled else "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "true" if enabled else "false"
    os.environ["LANGSMITH_HIDE_INPUTS"] = "true" if settings.hide_inputs else "false"
    os.environ["LANGSMITH_HIDE_OUTPUTS"] = "true" if settings.hide_outputs else "false"
    return enabled


def traced(name: str, run_type: str = "chain"):
    """Decorador que registra una función como un paso de la traza.

    :param name: Nombre del paso en LangSmith
    :type name: str
    :param run_type: ``chain``, ``llm`` o ``tool``
    :type run_type: str
    :return: El decorador de LangSmith
    """
    return traceable(name=name, run_type=run_type)
