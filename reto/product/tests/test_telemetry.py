"""Pruebas del log JSON de una linea por evento y del reloj del sistema."""

import io
import json
from datetime import datetime, timedelta

from conftest import FIXED_NOW, FakeClock

from app.clock import SystemClock
from app.telemetry import JsonLogger


def write_events(*emit_calls):
    """Emite eventos ligados a ``req-1`` y devuelve las lineas crudas."""
    stream = io.StringIO()
    emitter = JsonLogger(stream, FakeClock(), "hr-test").bind("req-1")
    for emit in emit_calls:
        emit(emitter)
    return stream.getvalue().splitlines()


def test_each_event_is_one_json_line_with_the_common_fields():
    lines = write_events(
        lambda log: log.request(
            method="GET", path="/health", status=200, latency_ms=12.5
        )
    )

    assert len(lines) == 1
    event = json.loads(lines[0])
    assert datetime.fromisoformat(event["ts"]) == FIXED_NOW
    assert datetime.fromisoformat(event["ts"]).utcoffset() == timedelta(0)
    assert event["service"] == "hr-test"
    assert event["event"] == "request"
    assert event["request_id"] == "req-1"
    assert (event["method"], event["path"]) == ("GET", "/health")
    assert (event["status"], event["latency_ms"]) == (200, 12.5)


def test_audit_and_error_events_keep_only_their_fields():
    lines = write_events(
        lambda log: log.audit(
            tool="search_by_department", args={"department": "Tecnología"}
        ),
        lambda log: log.error(error_type="RuntimeError"),
    )

    assert "Tecnología" in lines[0]
    audit, error = (json.loads(line) for line in lines)
    assert audit["action"] == "tool_call"
    assert audit["tool"] == "search_by_department"
    assert audit["args"] == {"department": "Tecnología"}
    assert error["event"] == "error"
    assert error["error_type"] == "RuntimeError"


def test_system_clock_returns_aware_utc_time():
    clock = SystemClock()

    assert clock.now().utcoffset() == timedelta(0)
    assert clock.monotonic() <= clock.monotonic()
