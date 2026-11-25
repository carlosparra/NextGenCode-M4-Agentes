"""Log estructurado en JSON, una línea por evento, con correlation id.

El ``request_id`` y el cliente viajan en variables de contexto, así cada
evento de una misma petición (API, agentes, herramientas, modelo, MCP) queda
ligado sin pasarlo a mano por todas las funciones.
"""

from __future__ import annotations

import json
import sys
import threading
from contextvars import ContextVar
from typing import Any, TextIO

from app.clock import Clock
from app.security.pii import mask_value

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
client_var: ContextVar[str] = ContextVar("client", default="-")
channel_var: ContextVar[str] = ContextVar("channel", default="api")


class JsonLogger:
    """Escribe eventos JSON en un flujo (stdout para la API, stderr para MCP).

    :param service: Nombre del servicio
    :type service: str
    :param clock: Reloj inyectado para el campo ``ts``
    :type clock: Clock
    :param stream: Flujo de salida
    :type stream: TextIO
    :param audit_path: Archivo JSONL adicional solo para auditoría (opcional)
    :type audit_path: str
    """

    def __init__(
        self,
        service: str,
        clock: Clock,
        stream: TextIO | None = None,
        audit_path: str = "",
    ) -> None:
        self._service = service
        self._clock = clock
        self._stream = stream
        self._audit_path = audit_path
        self._lock = threading.Lock()

    def event(self, name: str, **fields: Any) -> dict:
        """Registra un evento.

        Los campos de texto pasan por el enmascarado de PII por defensa en
        profundidad, aunque quien llama ya no debería mandar texto libre.

        :param name: Nombre del evento (``request``, ``agent_run``, ``audit``...)
        :type name: str
        :return: El registro escrito
        :rtype: dict
        """
        record = {
            "ts": self._clock.now().isoformat().replace("+00:00", "Z"),
            "service": self._service,
            "event": name,
            "request_id": request_id_var.get(),
            "client": client_var.get(),
            "channel": channel_var.get(),
            **mask_value(fields),
        }
        line = json.dumps(record, ensure_ascii=False, default=str)
        with self._lock:
            stream = self._stream or sys.stdout
            stream.write(line + "\n")
            stream.flush()
            if name == "audit" and self._audit_path:
                with open(self._audit_path, "a", encoding="utf-8") as audit_file:
                    audit_file.write(line + "\n")
        return record

    def audit(self, action: str, **fields: Any) -> dict:
        """Registra una acción relevante para auditoría.

        :param action: Acción (``tool_call``, ``auth_failed``, ``pii_detected``...)
        :type action: str
        :return: El registro escrito
        :rtype: dict
        """
        return self.event("audit", action=action, **fields)
