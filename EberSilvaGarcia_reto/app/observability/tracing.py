"""Trazas en LangSmith con datos personales protegidos.

- Sin ``LANGSMITH_TRACING=true`` y ``LANGSMITH_API_KEY`` no se conecta a nada.
- Con ``HIDE_INPUTS``/``HIDE_OUTPUTS`` en ``true`` no se manda ningún texto.
- Con ellos en ``false`` (solo desarrollo) el texto viaja con la PII enmascarada.

Los grafos de LangGraph se trazan solos dentro de :func:`trace_scope`: cada nodo,
cada llamada al modelo y cada herramienta aparecen como pasos anidados.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from app.config import Settings
from app.security.pii import mask_value


def _hide(enabled: bool):
    def hider(payload: dict) -> dict:
        return {"hidden": True} if enabled else mask_value(payload)

    return hider


class Tracer:
    """Envuelve la configuración de LangSmith del producto.

    :param settings: Configuración validada
    :type settings: Settings
    :param env: Variables de entorno (para leer la clave sin guardarla)
    :type env: dict | None
    """

    def __init__(self, settings: Settings, env: dict | None = None) -> None:
        env = dict(os.environ) if env is None else env
        self.project = settings.langsmith_project
        self.enabled = settings.langsmith_tracing and bool(env.get("LANGSMITH_API_KEY"))
        self._client = None
        if self.enabled:
            # pylint: disable=import-outside-toplevel
            from langsmith import Client

            self._client = Client(
                api_key=env.get("LANGSMITH_API_KEY"),
                hide_inputs=_hide(settings.hide_inputs),
                hide_outputs=_hide(settings.hide_outputs),
            )

    @contextmanager
    def scope(self, name: str, metadata: dict) -> Iterator[None]:
        """Abre el contexto de traza de una corrida.

        :param name: Nombre lógico (se agrega como etiqueta)
        :type name: str
        :param metadata: ``request_id``, ``client``, ``channel``... (nunca la clave)
        :type metadata: dict
        """
        # pylint: disable=import-outside-toplevel
        from langsmith import tracing_context

        if not self.enabled:
            with tracing_context(enabled=False):
                yield
            return
        with tracing_context(
            enabled=True,
            client=self._client,
            project_name=self.project,
            tags=[name],
            metadata=metadata,
        ):
            yield

    def flush(self) -> None:
        """Manda las trazas pendientes (útil al terminar scripts cortos)."""
        if self._client is not None:
            self._client.flush()
