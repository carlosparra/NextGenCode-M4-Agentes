"""Métricas del proceso: técnicas (latencia, errores, tokens) y de negocio.

Se exponen en JSON (``/metrics``) y en formato de texto de Prometheus
(``/metrics/prometheus``) para conectarlas a un tablero.
"""

from __future__ import annotations

import os
import threading
from collections import Counter, deque


def percentile(values: list[float], fraction: float) -> float:
    """Percentil por el método del rango más cercano.

    :param values: Muestras
    :type values: list[float]
    :param fraction: Percentil entre 0 y 1
    :type fraction: float
    :return: Valor del percentil (0 sin muestras)
    :rtype: float
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * len(ordered) + 0.5) - 1))
    return round(ordered[index], 2)


class Metrics:
    """Acumula métricas de forma segura entre hilos.

    :param slo_p95_ms: Meta de latencia p95
    :type slo_p95_ms: int
    :param window: Muestras de latencia que se conservan
    :type window: int
    """

    # pylint: disable=too-many-instance-attributes

    def __init__(self, slo_p95_ms: int, window: int = 1000) -> None:
        self._slo = slo_p95_ms
        self._lock = threading.Lock()
        self._latencies: deque[float] = deque(maxlen=window)
        self._agent_latencies: deque[float] = deque(maxlen=window)
        self.requests = 0
        self.errors = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cost_usd = 0.0
        self.cached_calls = 0
        self.model_calls = 0
        self.answer_cache_hits = 0
        self.counters: Counter[str] = Counter()

    def record_request(self, status: int, latency_ms: float) -> None:
        """Registra una petición HTTP.

        :param status: Código de respuesta
        :type status: int
        :param latency_ms: Latencia en milisegundos
        :type latency_ms: float
        """
        with self._lock:
            self.requests += 1
            self.errors += status >= 500
            self._latencies.append(latency_ms)
            self.counters[f"status_{status}"] += 1

    def record_agent(self, run: dict) -> None:
        """Suma los números de una corrida de agente.

        :param run: ``input_tokens``, ``output_tokens``, ``cost_usd``,
            ``cached_calls``, ``model_calls``, ``latency_ms``, ``intent``, ``model``
        :type run: dict
        """
        with self._lock:
            self.input_tokens += run.get("input_tokens", 0)
            self.output_tokens += run.get("output_tokens", 0)
            self.cost_usd += run.get("cost_usd", 0.0)
            self.cached_calls += run.get("cached_calls", 0)
            self.model_calls += run.get("model_calls", 0)
            self._agent_latencies.append(run.get("latency_ms", 0.0))
            self.counters[f"intent_{run.get('intent', 'other')}"] += 1
            self.counters[f"model_{run.get('model', 'none')}"] += 1
            for tool in run.get("tools", []):
                self.counters[f"tool_{tool}"] += 1

    def increment(self, name: str, amount: int = 1) -> None:
        """Suma a un contador con nombre.

        :param name: Nombre del contador
        :type name: str
        :param amount: Cuánto sumar
        :type amount: int
        """
        with self._lock:
            self.counters[name] += amount

    def snapshot(self) -> dict:
        """Estado actual de las métricas.

        :return: Métricas en el formato de ``GET /metrics``
        :rtype: dict
        """
        with self._lock:
            latencies = list(self._latencies)
            agent = list(self._agent_latencies)
            p95 = percentile(latencies, 0.95)
            return {
                "pid": os.getpid(),
                "requests": self.requests,
                "error_rate": (
                    round(self.errors / self.requests, 4) if self.requests else 0.0
                ),
                "latency_ms": {"p50": percentile(latencies, 0.5), "p95": p95},
                "agent_latency_ms": {
                    "p50": percentile(agent, 0.5),
                    "p95": percentile(agent, 0.95),
                    "p99": percentile(agent, 0.99),
                },
                "tokens": {"input": self.input_tokens, "output": self.output_tokens},
                "cost_usd": round(self.cost_usd, 8),
                "model_calls": self.model_calls,
                "cached_calls": self.cached_calls,
                "answer_cache_hits": self.answer_cache_hits,
                "slo": {"p95_ms_target": self._slo, "met": p95 < self._slo},
                "counters": dict(sorted(self.counters.items())),
            }

    def prometheus(self, service: str) -> str:
        """Métricas en formato de texto de Prometheus.

        :param service: Etiqueta ``service``
        :type service: str
        :return: Texto de exposición
        :rtype: str
        """
        snap = self.snapshot()
        label = f'service="{service}"'
        lines = [
            f"hr_requests_total{{{label}}} {snap['requests']}",
            f"hr_error_rate{{{label}}} {snap['error_rate']}",
            f"hr_latency_p50_ms{{{label}}} {snap['latency_ms']['p50']}",
            f"hr_latency_p95_ms{{{label}}} {snap['latency_ms']['p95']}",
            f"hr_tokens_input_total{{{label}}} {snap['tokens']['input']}",
            f"hr_tokens_output_total{{{label}}} {snap['tokens']['output']}",
            f"hr_cost_usd_total{{{label}}} {snap['cost_usd']}",
            f"hr_model_calls_total{{{label}}} {snap['model_calls']}",
            f"hr_cached_calls_total{{{label}}} {snap['cached_calls']}",
            f"hr_slo_met{{{label}}} {int(snap['slo']['met'])}",
        ]
        for name, value in snap["counters"].items():
            safe = "".join(c if c.isalnum() else "_" for c in name)
            lines.append(f'hr_events_total{{{label},name="{safe}"}} {value}')
        return "\n".join(lines) + "\n"
