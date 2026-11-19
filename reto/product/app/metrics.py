"""Metricas en memoria de este proceso para ``GET /metrics``.

Es estado de observacion, no de conversacion: cada proceso reporta las suyas
con su ``pid`` y se agregan por fuera (ADR 0005).
"""

import math
import os
import threading
from collections import deque

DEFAULT_LATENCY_WINDOW = 10_000
SERVER_ERROR_STATUS = 500


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


class Metrics:
    """Cuenta peticiones, errores, latencias, tokens y costo con un candado.

    :param window: Cuantas latencias recientes se guardan para los percentiles
    :type window: int
    """

    def __init__(self, window: int = DEFAULT_LATENCY_WINDOW):
        self._lock = threading.Lock()
        self._latencies = deque(maxlen=window)
        self._requests = 0
        self._errors = 0
        self._input_tokens = 0
        self._output_tokens = 0
        self._cost_usd = 0.0

    def record_request(self, status: int, latency_ms: float) -> None:
        """Registra una peticion atendida.

        :param status: Codigo HTTP; solo los 5xx cuentan como error
        :type status: int
        :param latency_ms: Duracion en milisegundos
        :type latency_ms: float
        """
        with self._lock:
            self._requests += 1
            if status >= SERVER_ERROR_STATUS:
                self._errors += 1
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
        """Suma el costo de una respuesta del agente.

        :param cost_usd: Costo en USD
        :type cost_usd: float
        """
        with self._lock:
            self._cost_usd += cost_usd

    def snapshot(self, slo_p95_ms: float) -> dict:
        """Devuelve las metricas actuales en el formato de ``GET /metrics``.

        :param slo_p95_ms: Meta de latencia p95 en milisegundos
        :type slo_p95_ms: float
        :return: ``pid``, ``requests``, ``error_rate``, ``latency_ms``,
            ``tokens``, ``cost_usd`` y ``slo``
        :rtype: dict
        """
        with self._lock:
            latencies = sorted(self._latencies)
            requests = self._requests
            errors = self._errors
            tokens = {"input": self._input_tokens, "output": self._output_tokens}
            cost_usd = self._cost_usd
        p95 = nearest_rank(latencies, 95)
        return {
            "pid": os.getpid(),
            "requests": requests,
            "error_rate": errors / requests if requests else 0,
            "latency_ms": {"p50": nearest_rank(latencies, 50), "p95": p95},
            "tokens": tokens,
            "cost_usd": cost_usd,
            "slo": {"p95_ms_target": slo_p95_ms, "met": p95 < slo_p95_ms},
        }
