"""Pruebas unitarias de las metricas en memoria del proceso.

Los percentiles usan el metodo de rango mas cercano (nearest rank):
el percentil ``p`` de ``n`` valores ordenados es el valor en la
posicion ``ceil(p / 100 * n)``.
"""

import os

from app.metrics import Metrics
from tests.conftest import SUPERVISOR_ROUTES_AT_ZERO


def _metrics(slo_p95_ms=2000):
    """Crea metricas nuevas con la meta indicada.

    :param slo_p95_ms: Meta de latencia p95 en ms.
    :type slo_p95_ms: int
    :return: Metricas vacias.
    :rtype: app.metrics.Metrics
    """
    return Metrics(slo_p95_ms=slo_p95_ms)


def test_new_metrics_report_zeros_and_this_process_pid():
    """Sin peticiones todo vale 0 y el SLO se cumple."""
    snapshot = _metrics().snapshot()
    assert snapshot == {
        "pid": os.getpid(),
        "requests": 0,
        "error_rate": 0,
        "latency_ms": {"p50": 0, "p95": 0},
        "tokens": {"input": 0, "output": 0},
        "cost_usd": 0,
        "slo": {"p95_ms_target": 2000, "met": True},
        "security": {
            "pii": 0,
            "secret": 0,
            "output_invalid": 0,
            "tool_args": 0,
            "injection": 0,
        },
        # Spec 06: conteo por especialista y por motivo del supervisor.
        "specialists": {"directory": 0, "policy": 0},
        "supervisor": SUPERVISOR_ROUTES_AT_ZERO,
    }


def test_percentiles_use_nearest_rank_and_tokens_add_up():
    """Percentiles con 1, 2 y 100 valores conocidos; tokens sumados."""
    one = _metrics()
    one.record_request(120, 200)
    assert one.snapshot()["latency_ms"] == {"p50": 120, "p95": 120}

    two = _metrics()
    two.record_request(10, 200)
    two.record_request(20, 200)
    assert two.snapshot()["latency_ms"] == {"p50": 10, "p95": 20}

    hundred = _metrics()
    for latency in range(100, 0, -1):
        hundred.record_request(latency, 200)
    hundred.record_tokens(10, 4)
    hundred.record_tokens(5, 1)
    snapshot = hundred.snapshot()
    assert snapshot["requests"] == 100
    assert snapshot["latency_ms"] == {"p50": 50, "p95": 95}
    assert snapshot["tokens"] == {"input": 15, "output": 5}


def test_error_rate_counts_only_server_errors():
    """Solo los 5xx cuentan como error; un 422 es del cliente."""
    metrics = _metrics()
    for status in (200, 422, 500, 503):
        metrics.record_request(10, status)
    assert metrics.snapshot()["error_rate"] == 0.5


def test_p95_equal_to_target_does_not_meet_the_slo():
    """El p95 debe quedar por debajo de la meta: igual no cumple."""
    at_target = _metrics(slo_p95_ms=2000)
    at_target.record_request(2000, 200)
    assert at_target.snapshot()["slo"] == {"p95_ms_target": 2000, "met": False}

    below = _metrics(slo_p95_ms=2000)
    below.record_request(1999, 200)
    assert below.snapshot()["slo"]["met"] is True
