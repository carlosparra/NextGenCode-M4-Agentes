"""Unit tests for the observability settings, JsonLogger and MetricsCollector."""

import io
import json
from datetime import datetime, timedelta

import pytest

from conftest import FakeClock

from app.config import load_settings
from app.observability import JsonLogger, MetricsCollector, request_id_var


def test_observability_defaults_are_safe():
    settings = load_settings({})
    assert settings.service_name == "hr-assistant"
    assert settings.slo_p95_ms == 2000
    assert settings.langsmith_tracing is False
    assert settings.hide_inputs is True
    assert settings.hide_outputs is True


def test_observability_values_can_be_overridden():
    settings = load_settings({
        "SERVICE_NAME": "hr-test",
        "SLO_P95_MS": "500",
        "LANGSMITH_TRACING": "true",
        "HIDE_INPUTS": "false",
        "HIDE_OUTPUTS": "false",
    })
    assert settings.service_name == "hr-test"
    assert settings.slo_p95_ms == 500
    assert settings.langsmith_tracing is True
    assert settings.hide_inputs is False
    assert settings.hide_outputs is False


@pytest.mark.parametrize("name, value", [
    ("SLO_P95_MS", "0"),
    ("SLO_P95_MS", "fast"),
    ("LANGSMITH_TRACING", "yes"),
    ("HIDE_INPUTS", "1"),
    ("HIDE_OUTPUTS", "maybe"),
])
def test_invalid_observability_values_are_rejected(name, value):
    with pytest.raises(ValueError):
        load_settings({name: value})


def test_logger_writes_one_json_line_with_required_fields():
    stream = io.StringIO()
    logger = JsonLogger("hr-test", FakeClock(), stream)
    request_id_var.set("req-1")
    logger.log("request", status=200)
    lines = stream.getvalue().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["service"] == "hr-test"
    assert entry["event"] == "request"
    assert entry["request_id"] == "req-1"
    assert entry["status"] == 200
    stamp = datetime.fromisoformat(entry["ts"].replace("Z", "+00:00"))
    assert stamp.utcoffset() == timedelta(0)
    assert stamp.year == 2026


def test_logger_escapes_newlines_so_a_value_cannot_forge_a_line():
    stream = io.StringIO()
    logger = JsonLogger("hr-test", FakeClock(), stream)
    request_id_var.set("req-2")
    logger.log("audit", note="first\n{\"event\": \"fake\"}")
    assert len(stream.getvalue().splitlines()) == 1


def test_metrics_with_no_requests_are_zero_and_meet_the_slo():
    snapshot = MetricsCollector(slo_p95_ms=2000).snapshot()
    assert snapshot["requests"] == 0
    assert snapshot["error_rate"] == 0
    assert snapshot["latency_ms"] == {"p50": 0, "p95": 0}
    assert snapshot["tokens"] == {"input": 0, "output": 0}
    assert snapshot["slo"] == {"p95_ms_target": 2000, "met": True}


def test_metrics_report_percentiles_error_rate_and_tokens():
    metrics = MetricsCollector(slo_p95_ms=2000)
    for latency in range(1, 101):
        metrics.record(latency, 500 if latency <= 10 else 200)
    metrics.add_tokens(7, 3)
    metrics.add_tokens(1, 2)
    snapshot = metrics.snapshot()
    assert snapshot["requests"] == 100
    assert snapshot["error_rate"] == pytest.approx(0.10)
    assert snapshot["latency_ms"]["p50"] == pytest.approx(50, abs=1)
    assert snapshot["latency_ms"]["p95"] == pytest.approx(95, abs=1)
    assert snapshot["tokens"] == {"input": 8, "output": 5}


def test_slo_is_not_met_when_p95_equals_the_target():
    metrics = MetricsCollector(slo_p95_ms=300)
    metrics.record(300, 200)
    assert metrics.snapshot()["latency_ms"]["p95"] == 300
    assert metrics.snapshot()["slo"]["met"] is False
