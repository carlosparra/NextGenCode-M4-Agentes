"""Log estructurado en JSON del HR Assistant.

Cada evento es una sola linea JSON con ``ts`` (ISO 8601 en UTC),
``service``, ``event`` y ``request_id``, mas los campos propios del
evento. La hora sale de un reloj inyectado.

:seealso: ``spec/02-observability.md``, punto 2.
"""

from __future__ import annotations

import json
import sys
import threading
from datetime import timezone
from typing import Any, TextIO

from app.clock import Clock, SystemClock


class JsonLogger:
    """Escribe eventos como lineas JSON en un stream.

    :param stream: Destino del log; por omision ``sys.stdout``.
    :type stream: typing.TextIO | None
    :param service: Nombre del servicio (campo ``service``).
    :type service: str
    :param clock: Reloj del que se obtiene ``ts``.
    :type clock: app.clock.Clock
    """

    def __init__(
        self,
        stream: TextIO | None = None,
        service: str = "hr-assistant",
        clock: Clock | None = None,
    ) -> None:
        """Guarda el destino, el servicio y el reloj.

        :param stream: Destino del log; por omision ``sys.stdout``.
        :type stream: typing.TextIO | None
        :param service: Nombre del servicio.
        :type service: str
        :param clock: Reloj inyectado; si falta, el del sistema.
        :type clock: app.clock.Clock | None
        """
        self._stream = stream
        self._service = service
        # Solo se usa el reloj real si no se inyecta otro.
        self._clock = clock if clock is not None else SystemClock()
        self._lock = threading.Lock()

    def emit(self, event: str, request_id: str, **fields: Any) -> None:
        """Escribe un evento como una linea JSON.

        :param event: Nombre del evento (``request``, ``audit``...).
        :type event: str
        :param request_id: Id de la peticion que origino el evento.
        :type request_id: str
        :param fields: Campos propios del evento.
        :type fields: Any
        """
        record = {
            "ts": self._clock.now().astimezone(timezone.utc).isoformat(),
            "service": self._service,
            "event": event,
            "request_id": request_id,
        }
        record.update(fields)
        line = json.dumps(record, ensure_ascii=False, default=str)
        stream = self._stream if self._stream is not None else sys.stdout
        with self._lock:
            stream.write(line + "\n")
            stream.flush()


class NullLogger:
    """Logger que descarta todo; util cuando no se inyecta uno."""

    def emit(self, event: str, request_id: str, **fields: Any) -> None:
        """No hace nada.

        :param event: Nombre del evento (ignorado).
        :type event: str
        :param request_id: Id de la peticion (ignorado).
        :type request_id: str
        :param fields: Campos del evento (ignorados).
        :type fields: Any
        """
