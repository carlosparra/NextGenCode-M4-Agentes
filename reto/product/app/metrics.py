"""Metricas en memoria de este proceso para ``GET /metrics``.

Es estado de observacion, no de conversacion: cada proceso reporta las suyas
con su ``pid`` y se agregan por fuera (ADR 0005 y 0016). Todo el estado se
protege con un solo ``threading.Lock``: FastAPI atiende ``POST /ask`` en su
pool de hilos.
"""

import math
import os
import threading
from collections import deque

DEFAULT_LATENCY_WINDOW = 10_000
CLIENT_ERROR_STATUS = 400
SERVER_ERROR_STATUS = 500
CLIENT_ERRORS = "4xx"
SERVER_ERRORS = "5xx"

# Contadores de seguridad de ``/metrics``; los alimentan las guardas.
SECURITY_AUTH_FAILURES = "auth_failures"
SECURITY_RATE_LIMITED = "rate_limited"
SECURITY_INPUTS_REJECTED = "inputs_rejected"
SECURITY_PII_DETECTIONS = "pii_detections"
SECURITY_OUTPUTS_BLOCKED = "outputs_blocked"
SECURITY_EVENTS = (
    SECURITY_AUTH_FAILURES,
    SECURITY_RATE_LIMITED,
    SECURITY_INPUTS_REJECTED,
    SECURITY_PII_DETECTIONS,
    SECURITY_OUTPUTS_BLOCKED,
)


def nearest_rank(sorted_values: list, percentile: float):
    """Calcula un percentil por el metodo de rango mas cercano.

    :param sorted_values: Valores ordenados de menor a mayor
    :type sorted_values: list[float]
    :param percentile: Percentil entre 0 y 100
    :type percentile: float
    :return: El valor del percentil, o 0 si no hay valores
    :rtype: float
    """
    if not sorted_values:
        return 0
    rank = max(1, math.ceil(percentile / 100 * len(sorted_values)))
    return sorted_values[rank - 1]


class Metrics:  # pylint: disable=too-many-instance-attributes
    """Cuenta peticiones, errores, latencias, tokens, costo, seguridad y cache.

    :param window: Cuantas latencias recientes se guardan para los percentiles
    :type window: int
    """

    def __init__(self, window: int = DEFAULT_LATENCY_WINDOW):
        self._lock = threading.Lock()
        self._latencies = deque(maxlen=window)
        self._requests = 0
        self._errors_by_status = {CLIENT_ERRORS: 0, SERVER_ERRORS: 0}
        self._input_tokens = 0
        self._output_tokens = 0
        self._cost_usd = 0.0
        self._costed_responses = 0
        self._security = dict.fromkeys(SECURITY_EVENTS, 0)
        self._cache = {"hits": 0, "misses": 0}

    def record_request(self, status: int, latency_ms: float) -> None:
        """Registra una peticion atendida.

        :param status: Codigo HTTP; los 4xx y 5xx se cuentan por familia y
            solo los 5xx cuentan para ``error_rate``
        :type status: int
        :param latency_ms: Duracion en milisegundos
        :type latency_ms: float
        """
        with self._lock:
            self._requests += 1
            if status >= SERVER_ERROR_STATUS:
                self._errors_by_status[SERVER_ERRORS] += 1
            elif status >= CLIENT_ERROR_STATUS:
                self._errors_by_status[CLIENT_ERRORS] += 1
            self._latencies.append(latency_ms)

    def add_tokens(self, input_tokens: int, output_tokens: int) -> None:
        """Suma los tokens de una respuesta del agente.

        :param input_tokens: Tokens de entrada
        :type input_tokens: int
        :param output_tokens: Tokens de salida
        :type output_tokens: int
        """
        with self._lock:
            self._input_tokens += input_tokens
            self._output_tokens += output_tokens

    def add_cost(self, cost_usd: float) -> None:
        """Suma el costo de una respuesta de ``/ask``.

        Se llama una vez por respuesta con costo, tambien con 0 (por ejemplo,
        un acierto de la cache), para que ``cost_usd_per_request`` promedie
        entre todas las respuestas.

        :param cost_usd: Costo en USD
        :type cost_usd: float
        """
        with self._lock:
            self._cost_usd += cost_usd
            self._costed_responses += 1

    def add_security_event(self, kind: str) -> None:
        """Cuenta un evento de seguridad.

        :param kind: Uno de ``SECURITY_EVENTS`` (``auth_failures``,
            ``rate_limited``, ``inputs_rejected``, ``pii_detections`` u
            ``outputs_blocked``)
        :type kind: str
        :raises KeyError: Si el tipo no es uno de ``SECURITY_EVENTS``
        """
        with self._lock:
            if kind not in self._security:
                raise KeyError(kind)
            self._security[kind] += 1

    def record_cache(self, hit: bool) -> None:
        """Cuenta un acierto o un fallo de la cache de respuestas.

        :param hit: ``True`` si la respuesta salio de la cache
        :type hit: bool
        """
        with self._lock:
            self._cache["hits" if hit else "misses"] += 1

    def snapshot(self, slo_p95_ms: float) -> dict:
        """Devuelve las metricas actuales en el formato de ``GET /metrics``.

        :param slo_p95_ms: Meta de latencia p95 en milisegundos
        :type slo_p95_ms: float
        :return: ``pid``, ``requests``, ``error_rate``, ``errors_by_status``,
            ``latency_ms``, ``tokens``, ``cost_usd``, ``cost_usd_per_request``,
            ``security``, ``cache`` y ``slo``
        :rtype: dict
        """
        with self._lock:
            latencies = sorted(self._latencies)
            requests = self._requests
            errors_by_status = dict(self._errors_by_status)
            tokens = {"input": self._input_tokens, "output": self._output_tokens}
            cost_usd = self._cost_usd
            costed = self._costed_responses
            security = dict(self._security)
            cache = dict(self._cache)
        p95 = nearest_rank(latencies, 95)
        server_errors = errors_by_status[SERVER_ERRORS]
        return {
            "pid": os.getpid(),
            "requests": requests,
            "error_rate": server_errors / requests if requests else 0,
            "errors_by_status": errors_by_status,
            "latency_ms": {"p50": nearest_rank(latencies, 50), "p95": p95},
            "tokens": tokens,
            "cost_usd": cost_usd,
            "cost_usd_per_request": cost_usd / costed if costed else 0.0,
            "security": security,
            "cache": cache,
            "slo": {"p95_ms_target": slo_p95_ms, "met": p95 < slo_p95_ms},
        }
