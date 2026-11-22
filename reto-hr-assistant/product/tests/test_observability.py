"""Pruebas unitarias de reloj, log JSON, métricas, id de petición y trazas."""

import io
import json
import sys
import types
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta

from app.clock import SystemClock
from app.config import load_settings
from app.logs import JsonLogger
from app.metrics import Metrics
from app.middleware import resolve_request_id
from app.tracing import Tracer


def test_system_clock_returns_utc_time():
    clock = SystemClock()

    assert clock.now().utcoffset() == timedelta(0)
    assert isinstance(clock.monotonic(), float)


def test_logger_writes_one_json_line_with_base_fields_first(make_clock):
    clock = make_clock()
    stream = io.StringIO()
    logger = JsonLogger("hr-demo", clock, stream=stream)

    logger.emit("audit", "req-1", tool="get_employee", owner="Jorge Díaz")

    lines = stream.getvalue().splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert list(event)[:4] == ["ts", "service", "event", "request_id"]
    assert datetime.fromisoformat(event["ts"]) == clock.now()
    assert (event["service"], event["event"], event["request_id"]) == (
        "hr-demo",
        "audit",
        "req-1",
    )
    assert event["tool"] == "get_employee"
    assert "Jorge Díaz" in lines[0]


def test_percentiles_use_nearest_rank_with_zero_one_and_many_latencies():
    empty, single, many = (Metrics(slo_p95_ms=2000) for _ in range(3))
    single.record_request(200, 42)
    for latency in range(1, 101):
        many.record_request(200, latency)

    empty_snapshot = empty.snapshot()
    assert empty_snapshot["requests"] == 0
    assert empty_snapshot["error_rate"] == 0.0
    assert empty_snapshot["latency_ms"] == {"p50": 0, "p95": 0}
    assert single.snapshot()["latency_ms"] == {"p50": 42, "p95": 42}
    assert many.snapshot()["latency_ms"] == {"p50": 50, "p95": 95}
    assert many.snapshot()["slo"] == {"p95_ms_target": 2000, "met": True}


def test_error_rate_counts_only_server_errors_and_tokens_add_up():
    metrics = Metrics(slo_p95_ms=2000)
    for status in (200, 404, 422, 500, 503):
        metrics.record_request(status, 10)
    metrics.add_tokens(10, 2)
    metrics.add_tokens(5, 1)

    snapshot = metrics.snapshot()

    assert snapshot["requests"] == 5
    assert snapshot["error_rate"] == 0.4
    assert snapshot["tokens"] == {"input": 15, "output": 3}


def test_latency_window_keeps_only_the_latest_thousand_requests():
    metrics = Metrics(slo_p95_ms=2000)
    for _ in range(1000):
        metrics.record_request(200, 5000)
    assert metrics.snapshot()["slo"]["met"] is False

    for _ in range(1000):
        metrics.record_request(200, 1)

    snapshot = metrics.snapshot()
    assert snapshot["requests"] == 2000
    assert snapshot["latency_ms"] == {"p50": 1, "p95": 1}
    assert snapshot["slo"]["met"] is True


def test_request_id_header_is_kept_only_when_short_and_safe():
    assert resolve_request_id("demo-123") == "demo-123"
    assert resolve_request_id("a.B_9-" * 21 + "ab") == "a.B_9-" * 21 + "ab"

    for unsafe in (None, "", "a" * 129, "abc\ndef", "bad id", "<script>"):
        assert uuid.UUID(resolve_request_id(unsafe)).version == 4


def test_disabled_tracer_returns_the_same_function_without_loading_langsmith(
    monkeypatch,
):
    monkeypatch.setitem(sys.modules, "langsmith", None)
    tracer = Tracer(load_settings({"LANGSMITH_TRACING": "true"}))

    def double(number):
        return number * 2

    assert tracer.wrap(double, "double", "tool") is double
    with tracer.request_scope("req-1"):
        assert double(2) == 4


def test_enabled_tracer_hides_texts_and_tags_the_request_id(monkeypatch):
    calls = {"traceable": []}

    class FakeClient:  # pylint: disable=too-few-public-methods
        """Cliente de LangSmith simulado que anota cómo se creó."""

        def __init__(self, **kwargs):
            calls["client"] = kwargs

    def traceable(*args, **kwargs):
        calls["traceable"].append(kwargs)
        if args and callable(args[0]):
            return args[0]
        return lambda function: function

    @contextmanager
    def tracing_context(**kwargs):
        calls["context"] = kwargs
        yield

    fake_langsmith = types.ModuleType("langsmith")
    fake_langsmith.Client = FakeClient
    fake_langsmith.traceable = traceable
    fake_langsmith.tracing_context = tracing_context
    monkeypatch.setitem(sys.modules, "langsmith", fake_langsmith)
    settings = load_settings(
        {"LANGSMITH_TRACING": "true", "LANGSMITH_API_KEY": "test-key"}
    )

    tracer = Tracer(settings)
    wrapped = tracer.wrap(lambda number: number + 1, "add_one", "tool")
    with tracer.request_scope("req-7"):
        assert wrapped(1) == 2

    assert calls["client"]["hide_inputs"] is True
    assert calls["client"]["hide_outputs"] is True
    assert calls["traceable"][0]["name"] == "add_one"
    assert calls["traceable"][0]["run_type"] == "tool"
    assert calls["context"]["metadata"] == {"request_id": "req-7"}
