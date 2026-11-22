"""Métricas del proceso: peticiones, errores, latencias, tokens, SLO y PII."""

import math
import os
import threading
from collections import deque

LATENCY_WINDOW = 1000
SERVER_ERROR_STATUS = 500
# Los costos por respuesta son fracciones de centavo: se redondean muy abajo.
COST_DECIMALS = 10
PII_DIRECTIONS = ("input", "output")


def nearest_rank(sorted_values: list, percentile: float):
    """Calcula un percentil por el método del rango más cercano.

    :param sorted_values: Valores ordenados de menor a mayor
    :type sorted_values: list[float]
    :param percentile: Percentil entre 0 y 100
    :type percentile: float
    :return: Valor del percentil; 0 si no hay valores
    :rtype: float
    """
    if not sorted_values:
        return 0
    rank = max(1, math.ceil(percentile / 100 * len(sorted_values)))
    return sorted_values[rank - 1]


class Metrics:
    """Contadores de este proceso, seguros entre hilos.

    Se pierden al reiniciar y no afectan a ninguna respuesta.

    :param slo_p95_ms: Meta de latencia p95 en milisegundos
    :type slo_p95_ms: int
    :param window: Número máximo de latencias que se guardan
    :type window: int
    """

    def __init__(self, slo_p95_ms: int, window: int = LATENCY_WINDOW):
        self._slo_p95_ms = slo_p95_ms
        self._lock = threading.Lock()
        self._latencies = deque(maxlen=window)
        # Peticiones terminadas y cuántas fueron errores del servidor.
        self._counts = {"requests": 0, "errors": 0}
        self._tokens = {"input": 0, "output": 0}
        self._cost_usd = 0.0
        self._pii = {direction: {} for direction in PII_DIRECTIONS}

    def record_pii(self, direction: str, types: list) -> None:
        """Cuenta una detección de PII: uno por tipo, no por ocurrencia.

        :param direction: ``input`` (pregunta) u ``output`` (respuesta)
        :type direction: str
        :param types: Tipos encontrados, sin valores
        :type types: list[str]
        :raises ValueError: Si la dirección no es ``input`` ni ``output``
        """
        if direction not in PII_DIRECTIONS:
            raise ValueError(f"unknown PII direction: {direction!r}")
        with self._lock:
            counts = self._pii[direction]
            for pii_type in dict.fromkeys(types):
                counts[pii_type] = counts.get(pii_type, 0) + 1

    def record_request(self, status: int, latency_ms: float) -> None:
        """Registra una petición terminada.

        :param status: Código HTTP de la respuesta
        :type status: int
        :param latency_ms: Latencia en milisegundos
        :type latency_ms: float
        """
        with self._lock:
            self._counts["requests"] += 1
            if status >= SERVER_ERROR_STATUS:
                self._counts["errors"] += 1
            self._latencies.append(latency_ms)

    def add_tokens(self, input_tokens: int, output_tokens: int) -> None:
        """Suma los tokens de una corrida del agente.

        :param input_tokens: Tokens de entrada
        :type input_tokens: int
        :param output_tokens: Tokens de salida
        :type output_tokens: int
        """
        with self._lock:
            self._tokens["input"] += input_tokens
            self._tokens["output"] += output_tokens

    def add_cost(self, cost_usd: float) -> None:
        """Suma el costo de una respuesta.

        :param cost_usd: Costo en USD
        :type cost_usd: float
        """
        with self._lock:
            self._cost_usd += cost_usd

    def snapshot(self) -> dict:
        """Devuelve el resumen que sirve ``GET /metrics``.

        :return: ``pid``, ``requests``, ``error_rate``, ``latency_ms``, ``tokens``,
            ``cost_usd``, ``slo`` y ``pii_detections``
        :rtype: dict
        """
        with self._lock:
            requests = self._counts["requests"]
            errors = self._counts["errors"]
            latencies = sorted(self._latencies)
            tokens = dict(self._tokens)
            cost_usd = self._cost_usd
            pii = {direction: dict(counts) for direction, counts in self._pii.items()}
        p95 = round(nearest_rank(latencies, 95), 3)
        return {
            "pid": os.getpid(),
            "requests": requests,
            "error_rate": round(errors / requests, 4) if requests else 0.0,
            "latency_ms": {"p50": round(nearest_rank(latencies, 50), 3), "p95": p95},
            "tokens": tokens,
            "cost_usd": round(cost_usd, COST_DECIMALS),
            "slo": {"p95_ms_target": self._slo_p95_ms, "met": p95 < self._slo_p95_ms},
            "pii_detections": pii,
        }
