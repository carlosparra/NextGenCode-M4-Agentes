"""Pruebas de las metricas en memoria del proceso."""

import os
import random
import threading

import pytest

from app.metrics import Metrics


def test_metrics_without_samples_report_zero_and_meet_the_slo():
    snapshot = Metrics().snapshot(slo_p95_ms=2000)

    assert snapshot["pid"] == os.getpid()
    assert snapshot["requests"] == 0
    assert snapshot["error_rate"] == 0
    assert snapshot["latency_ms"] == {"p50": 0, "p95": 0}
    assert snapshot["tokens"] == {"input": 0, "output": 0}
    assert snapshot["slo"] == {"p95_ms_target": 2000, "met": True}


def test_percentiles_use_the_nearest_rank():
    metrics = Metrics()
    latencies = list(range(1, 101))
    random.Random(7).shuffle(latencies)
    for latency in latencies:
        metrics.record_request(status=200, latency_ms=latency)

    assert metrics.snapshot(slo_p95_ms=2000)["latency_ms"] == {"p50": 50, "p95": 95}


def test_only_server_errors_count_toward_the_error_rate():
    metrics = Metrics()
    for status in (200, 404, 422, 500):
        metrics.record_request(status=status, latency_ms=10)
    metrics.add_tokens(input_tokens=10, output_tokens=2)
    metrics.add_tokens(input_tokens=5, output_tokens=1)

    snapshot = metrics.snapshot(slo_p95_ms=2000)

    assert snapshot["requests"] == 4
    assert snapshot["error_rate"] == pytest.approx(0.25)
    assert snapshot["tokens"] == {"input": 15, "output": 3}


def test_slo_is_not_met_when_p95_equals_the_target():
    metrics = Metrics()
    metrics.record_request(status=200, latency_ms=2000)

    assert metrics.snapshot(slo_p95_ms=2000)["slo"]["met"] is False


def test_concurrent_requests_are_all_counted():
    metrics = Metrics()

    def record_many():
        for _ in range(250):
            metrics.record_request(status=200, latency_ms=1)

    threads = [threading.Thread(target=record_many) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert metrics.snapshot(slo_p95_ms=2000)["requests"] == 2000
