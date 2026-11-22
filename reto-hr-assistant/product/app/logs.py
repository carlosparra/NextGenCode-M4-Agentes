"""Log estructurado: una línea JSON por evento en la salida estándar."""

import json
import sys
import threading

BASE_FIELDS = ("ts", "service", "event", "request_id")


class JsonLogger:
    """Escribe eventos como líneas JSON con los campos base primero.

    :param service: Nombre del servicio (campo ``service``)
    :type service: str
    :param clock: Reloj que da la hora de cada evento
    :type clock: app.clock.Clock
    :param stream: Flujo de salida; por omisión ``sys.stdout``
    :type stream: typing.TextIO or None
    """

    def __init__(self, service: str, clock, stream=None):
        self._service = service
        self._clock = clock
        self._stream = stream if stream is not None else sys.stdout
        self._lock = threading.Lock()

    def emit(self, event: str, request_id: str, **fields) -> None:
        """Escribe un evento en una sola línea JSON y vacía el flujo.

        Los campos extra no pueden reemplazar a los campos base.

        :param event: Nombre del evento (``request``, ``audit``, ...)
        :type event: str
        :param request_id: Id de la petición a la que pertenece el evento
        :type request_id: str
        :param fields: Campos propios del evento
        :type fields: dict
        """
        record = {
            "ts": self._clock.now().isoformat(),
            "service": self._service,
            "event": event,
            "request_id": request_id,
        }
        record.update(
            (name, value) for name, value in fields.items() if name not in BASE_FIELDS
        )
        line = json.dumps(record, ensure_ascii=False, default=str)
        with self._lock:
            self._stream.write(line + "\n")
            self._stream.flush()
