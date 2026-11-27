"""Log estructurado: una línea JSON por evento, con el contexto de la petición.

Nunca se escribe el texto de preguntas o respuestas, ni claves.
"""

import json
import sys
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
client_var: ContextVar[str] = ContextVar("client", default="-")
channel_var: ContextVar[str] = ContextVar("channel", default="-")


def trace_metadata() -> dict:
    """Contexto de la petición, para los metadatos de una traza.

    :return: ``request_id``, ``client`` y ``channel`` de la petición en curso
    :rtype: dict
    """
    return {
        "request_id": request_id_var.get(),
        "client": client_var.get(),
        "channel": channel_var.get(),
    }


class JsonLogger:
    """Escribe eventos en JSON con ``ts``, ``service``, ``event`` y ``request_id``."""

    def __init__(self, service: str, clock, stream=None):
        self._service = service
        self._clock = clock
        self._stream = stream

    def event(self, name: str, **fields) -> None:
        """Escribe un evento.

        :param name: ``request``, ``agent_run``, ``audit``, ``security`` o ``error``
        :type name: str
        :param fields: Campos propios del evento
        """
        record = {
            "ts": self._clock.now().isoformat(),
            "service": self._service,
            "event": name,
            "request_id": request_id_var.get(),
            "client": client_var.get(),
            "channel": channel_var.get(),
            **fields,
        }
        stream = self._stream or sys.stdout
        stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        stream.flush()

    def audit(self, action: str, **fields) -> None:
        """Escribe un evento de auditoría.

        :param action: Qué pasó, por ejemplo ``tool_call`` o ``auth_failed``
        :type action: str
        :param fields: Detalle de la acción, sin datos personales
        """
        self.event("audit", action=action, **fields)
