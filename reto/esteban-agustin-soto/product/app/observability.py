"""Reloj inyectable, log JSON por evento y métricas del proceso."""

import json
import math
import sys
import threading
from collections import deque
from contextvars import ContextVar
from datetime import datetime, timezone

from app.pii import mask_deep, mask_text

DEFAULT_REQUEST_ID = "-"
LATENCY_WINDOW = 1000

request_id_var = ContextVar("request_id", default=DEFAULT_REQUEST_ID)


client_var = ContextVar("client", default=None)


class Clock:
    """Reloj del sistema; único lugar donde se lee la hora real."""

    def now(self):
        """Da el instante actual.

        :return: Fecha y hora con zona horaria UTC
        :rtype: datetime.datetime
        """
        return datetime.now(timezone.utc)


class JsonLogger:
    """Escribe una línea JSON por evento.

    :param service: Valor del campo ``service``
    :type service: str
    :param clock: Objeto con ``now()``
    :type clock: object
    :param stream: Destino de las líneas; por omisión la salida estándar
    :type stream: typing.TextIO or None
    :param masking: Si se enmascaran CURP y correo en los valores de los campos
    :type masking: bool
    """

    def __init__(self, service, clock, stream=None, masking=True):
        self._service = service
        self._clock = clock
        self._stream = stream
        self._masking = masking
        self._lock = threading.Lock()

    def _serialize(self, entry):
        """Serializa la entrada; enmascara los valores antes, no la línea.

        :param entry: Campos del evento
        :type entry: dict
        :return: Una línea JSON
        :rtype: str
        """
        if not self._masking:
            return json.dumps(entry, ensure_ascii=True, default=str)
        return json.dumps(
            mask_deep(entry), ensure_ascii=True,
            default=lambda value: mask_text(str(value)),
        )

    def log(self, event, **fields):
        """Escribe un evento con ``ts``, ``service``, ``event`` y ``request_id``.

        Si hay un cliente en ``client_var`` agrega también ``client``.

        :param event: Nombre del evento
        :type event: str
        :param fields: Campos propios del evento
        :type fields: object
        """
        stamp = self._clock.now().astimezone(timezone.utc)
        entry = dict(fields)
        entry.update({
            "ts": stamp.isoformat(),
            "service": self._service,
            "event": event,
            "request_id": request_id_var.get(),
        })
        client = client_var.get()
        if client is not None:
            entry["client"] = client
        line = self._serialize(entry)
        stream = self._stream or sys.stdout
        with self._lock:
            stream.write(line + "\n")
            stream.flush()


def _percentile(sorted_values, fraction):
    """Calcula un percentil por rango más cercano.

    :param sorted_values: Valores ordenados de menor a mayor
    :type sorted_values: list
    :param fraction: Fracción entre 0 y 1
    :type fraction: float
    :return: El percentil, o 0 si no hay valores
    :rtype: float
    """
    if not sorted_values:
        return 0
    rank = max(math.ceil(fraction * len(sorted_values)) - 1, 0)
    return sorted_values[rank]


class MetricsCollector:  # pylint: disable=too-many-instance-attributes
    """Métricas en memoria de este proceso, seguras entre hilos.

    :param slo_p95_ms: Meta de latencia p95 en milisegundos
    :type slo_p95_ms: int
    """

    def __init__(self, slo_p95_ms):
        self._slo = slo_p95_ms
        self._lock = threading.Lock()
        self._latencies = deque(maxlen=LATENCY_WINDOW)
        self._requests = 0
        self._errors = 0
        self._input_tokens = 0
        self._output_tokens = 0
        self._cost_usd = 0.0

    def record(self, latency_ms, status):
        """Registra una petición terminada.

        :param latency_ms: Latencia en milisegundos
        :type latency_ms: float
        :param status: Código HTTP de la respuesta
        :type status: int
        """
        with self._lock:
            self._requests += 1
            self._latencies.append(latency_ms)
            if status >= 500:
                self._errors += 1

    def add_tokens(self, input_tokens, output_tokens):
        """Suma los tokens de una corrida del agente.

        :param input_tokens: Tokens de entrada
        :type input_tokens: int
        :param output_tokens: Tokens de salida
        :type output_tokens: int
        """
        with self._lock:
            self._input_tokens += input_tokens
            self._output_tokens += output_tokens

    def add_cost(self, usd):
        """Suma el costo de una respuesta.

        :param usd: Costo en dólares
        :type usd: float
        """
        with self._lock:
            self._cost_usd += usd

    def snapshot(self):
        """Resume las cifras (todo lo de ``/metrics`` salvo ``pid``).

        :return: Peticiones, tasa de error, latencias, tokens, costo y SLO
        :rtype: dict
        """
        with self._lock:
            ordered = sorted(self._latencies)
            requests = self._requests
            errors = self._errors
            tokens = {"input": self._input_tokens,
                      "output": self._output_tokens}
            cost_usd = self._cost_usd
        p95 = _percentile(ordered, 0.95)
        return {
            "requests": requests,
            "error_rate": errors / requests if requests else 0,
            "latency_ms": {"p50": _percentile(ordered, 0.50), "p95": p95},
            "tokens": tokens,
            "cost_usd": cost_usd,
            "slo": {"p95_ms_target": self._slo, "met": p95 < self._slo},
        }
