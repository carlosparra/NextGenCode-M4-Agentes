"""Métricas de este proceso: técnicas (latencia, errores) y de negocio (costo, uso)."""

import math
import os
import threading
from collections import Counter, deque

MAX_SAMPLES = 2000
ERROR_STATUS = 500


def percentile(values: list[float], fraction: float) -> float:
    """Percentil por el método del rango más cercano.

    :param values: Muestras
    :type values: list[float]
    :param fraction: Percentil entre 0 y 1, por ejemplo 0.95
    :type fraction: float
    :return: El valor del percentil, o 0 sin muestras
    :rtype: float
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


class Metrics:  # pylint: disable=too-many-instance-attributes
    """Contadores en memoria, seguros entre hilos."""

    def __init__(self, slo_p95_ms: float):
        self._slo = slo_p95_ms
        self._lock = threading.Lock()
        self._latencies: deque = deque(maxlen=MAX_SAMPLES)
        self._requests = 0
        self._errors = 0
        self._tokens = Counter()
        self._cost = 0.0
        self._baseline_cost = 0.0
        self._counters = Counter()

    def record_request(self, status: int, latency_ms: float) -> None:
        """Cuenta una petición HTTP.

        :param status: Código de respuesta
        :type status: int
        :param latency_ms: Tiempo de respuesta en milisegundos
        :type latency_ms: float
        """
        with self._lock:
            self._requests += 1
            self._errors += status >= ERROR_STATUS
            self._latencies.append(latency_ms)
            self._counters[f"status_{status}"] += 1

    def record_run(self, run: dict, baseline_cost: float) -> None:
        """Cuenta una corrida de agente.

        :param run: Respuesta de ``HRService`` (tokens, costo, modelo, agente)
        :type run: dict
        :param baseline_cost: Lo que habría costado con el modelo grande
        :type baseline_cost: float
        """
        with self._lock:
            self._tokens["input"] += run["input_tokens"]
            self._tokens["output"] += run["output_tokens"]
            self._cost += run["cost_usd"]
            self._baseline_cost += baseline_cost
            self._counters[f"agent_{run['agent']}"] += 1
            self._counters[f"model_{run['model']}"] += 1
            self._counters["gateway_cached_calls"] += run["cached_calls"]
            self._counters["response_cache_hits"] += run["cache"] == "hit"
            self._counters["pii_masked"] += bool(run["pii_masked"])

    def count(self, name: str) -> None:
        """Suma uno a un contador con nombre.

        :param name: Contador, por ejemplo ``guard_blocked``
        :type name: str
        """
        with self._lock:
            self._counters[name] += 1

    def snapshot(self) -> dict:
        """Estado actual de las métricas.

        :return: Peticiones, tasa de error, latencias, tokens, costo y SLO
        :rtype: dict
        """
        with self._lock:
            latencies = list(self._latencies)
            p95 = percentile(latencies, 0.95)
            saved = self._baseline_cost - self._cost
            return {
                "pid": os.getpid(),
                "requests": self._requests,
                "error_rate": self._errors / self._requests if self._requests else 0.0,
                "latency_ms": {
                    "p50": round(percentile(latencies, 0.5), 2),
                    "p95": round(p95, 2),
                },
                "tokens": {
                    "input": self._tokens["input"],
                    "output": self._tokens["output"],
                },
                "cost_usd": round(self._cost, 8),
                "baseline_cost_usd": round(self._baseline_cost, 8),
                "savings_pct": (
                    round(100 * saved / self._baseline_cost, 1)
                    if self._baseline_cost
                    else 0.0
                ),
                "slo": {"p95_ms_target": self._slo, "met": p95 < self._slo},
                "counters": dict(sorted(self._counters.items())),
            }

    def prometheus(self, service: str) -> str:
        """Las mismas métricas en el formato de texto de Prometheus.

        :param service: Nombre del servicio, para la etiqueta ``service``
        :type service: str
        :return: Texto con una métrica por línea
        :rtype: str
        """
        data = self.snapshot()
        label = f'{{service="{service}"}}'
        lines = [
            f"hr_requests_total{label} {data['requests']}",
            f"hr_error_rate{label} {data['error_rate']}",
            f"hr_latency_p50_ms{label} {data['latency_ms']['p50']}",
            f"hr_latency_p95_ms{label} {data['latency_ms']['p95']}",
            f"hr_tokens_input_total{label} {data['tokens']['input']}",
            f"hr_tokens_output_total{label} {data['tokens']['output']}",
            f"hr_cost_usd_total{label} {data['cost_usd']}",
            f"hr_slo_met{label} {int(data['slo']['met'])}",
        ]
        for name, value in data["counters"].items():
            safe = "".join(c if c.isalnum() else "_" for c in name)
            labels = f'{{service="{service}",name="{safe}"}}'
            lines.append(f"hr_events_total{labels} {value}")
        return "\n".join(lines) + "\n"
