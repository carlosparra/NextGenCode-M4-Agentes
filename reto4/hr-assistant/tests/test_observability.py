"""Pruebas unitarias de la observabilidad (``app.observability``).

Ninguna prueba toca la red: el módulo ``langsmith`` se reemplaza por un doble
que se pasa en ``loader``.
"""

import contextlib
import io
import json
import types
from datetime import datetime, timezone

import pytest

from app.config import ConfigError, load_config
from app.observability import JsonLogger, Metrics, NullTracer, build_tracer

FIXED_NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
TRACING_ENV = {"LANGSMITH_TRACING": "true", "LANGSMITH_API_KEY": "test-key"}


class FixedClock:
    """Reloj de prueba que siempre da la misma hora."""

    def now(self):
        """Devuelve la hora fija.

        :return: Hora fija en UTC
        :rtype: datetime.datetime
        """
        return FIXED_NOW

    def monotonic(self):
        """Devuelve un contador fijo.

        :return: Cero segundos
        :rtype: float
        """
        return 0.0


def fail_if_called(name):
    """Loader que hace fallar la prueba si alguien intenta importar.

    :param name: Módulo que se intentó importar
    :type name: str
    :raises AssertionError: Siempre
    """
    raise AssertionError(f"{name} must not be imported")


def fake_langsmith(traceable_error=None):
    """Arma un doble del módulo ``langsmith`` que guarda lo que recibe.

    :param traceable_error: Error que lanza ``traceable``; ``None`` si no falla
    :type traceable_error: Exception or None
    :return: Módulo falso con ``Client``, ``traceable``, ``tracing_context``
        y la lista ``records`` de lo recibido
    :rtype: types.SimpleNamespace
    """
    records = {"client": None, "traceable": []}

    def client(**kwargs):
        records["client"] = kwargs
        return "fake-client"

    def traceable(**kwargs):
        if traceable_error is not None:
            raise traceable_error
        records["traceable"].append(kwargs)
        return lambda function: function

    @contextlib.contextmanager
    def tracing_context(**_kwargs):
        yield

    return types.SimpleNamespace(
        Client=client,
        traceable=traceable,
        tracing_context=tracing_context,
        records=records,
    )


def test_log_line_is_json_with_the_injected_clock_time():
    stream = io.StringIO()
    logger = JsonLogger("hr-assistant", FixedClock(), stream)

    logger.log("request", "req-1", status=200)

    assert json.loads(stream.getvalue()) == {
        "ts": "2026-01-02T03:04:05+00:00",
        "service": "hr-assistant",
        "event": "request",
        "request_id": "req-1",
        "status": 200,
    }


def test_latency_percentiles_use_the_recorded_samples():
    metrics = Metrics(slo_p95_ms=2000)
    for latency in range(1, 101):
        metrics.record_request(200, float(latency))

    latency_ms = metrics.snapshot(pid=1)["latency_ms"]

    assert latency_ms == {"p50": 50.0, "p95": 95.0}


def test_error_rate_counts_only_server_errors():
    metrics = Metrics(slo_p95_ms=2000)
    for status in (200, 422, 500, 502):
        metrics.record_request(status, 10.0)

    snapshot = metrics.snapshot(pid=1)

    assert snapshot["requests"] == 4
    assert snapshot["error_rate"] == 0.5


def test_metrics_without_requests_report_zero():
    snapshot = Metrics(slo_p95_ms=2000).snapshot(pid=7)

    assert snapshot["pid"] == 7
    assert snapshot["requests"] == 0
    assert snapshot["error_rate"] == 0
    assert snapshot["latency_ms"] == {"p50": 0, "p95": 0}


def test_slo_is_met_only_when_p95_is_below_the_target():
    fast = Metrics(slo_p95_ms=100)
    slow = Metrics(slo_p95_ms=100)
    fast.record_request(200, 99.0)
    slow.record_request(200, 100.0)

    assert fast.snapshot(pid=1)["slo"] == {"p95_ms_target": 100, "met": True}
    assert slow.snapshot(pid=1)["slo"] == {"p95_ms_target": 100, "met": False}


def test_tokens_and_cost_accumulate_across_runs():
    metrics = Metrics(slo_p95_ms=2000)

    metrics.record_run(input_tokens=100, output_tokens=20, cost_usd=0.001)
    metrics.record_run(input_tokens=50, output_tokens=10, cost_usd=0.002)

    snapshot = metrics.snapshot(pid=1)
    assert snapshot["tokens"] == {"input": 150, "output": 30}
    assert snapshot["cost_usd"] == pytest.approx(0.003)


@pytest.mark.parametrize(
    "environ",
    [
        {"LANGSMITH_TRACING": "true"},
        {"LANGSMITH_TRACING": "false", "LANGSMITH_API_KEY": "test-key"},
    ],
    ids=["without_api_key", "with_tracing_disabled"],
)
def test_tracer_is_null_and_imports_nothing(environ):
    tracer = build_tracer(load_config(environ), loader=fail_if_called)

    def function():
        return "ok"

    assert isinstance(tracer, NullTracer)
    assert tracer.wrap(function, "agent", "chain", "req-1") is function


def test_tracer_client_respects_hide_settings_and_tags_the_request_id():
    module = fake_langsmith()
    environ = {**TRACING_ENV, "HIDE_OUTPUTS": "false"}
    tracer = build_tracer(load_config(environ), loader=lambda _name: module)

    traced = tracer.wrap(lambda: "ok", "agent", "chain", "req-42")

    assert traced() == "ok"
    assert module.records["client"] == {
        "api_key": "test-key",
        "hide_inputs": True,
        "hide_outputs": False,
    }
    assert module.records["traceable"][0]["metadata"] == {"request_id": "req-42"}


def test_tracer_returns_the_original_function_when_wrapping_fails():
    module = fake_langsmith(traceable_error=RuntimeError("tracer broken"))
    tracer = build_tracer(load_config(TRACING_ENV), loader=lambda _name: module)

    def function():
        return "ok"

    assert tracer.wrap(function, "agent", "chain", "req-1") is function


def test_tracer_tags_the_client_in_the_trace_metadata():
    module = fake_langsmith()
    tracer = build_tracer(load_config(TRACING_ENV), loader=lambda _name: module)

    def function():
        return "ok"

    traced = tracer.wrap(function, "agent", "chain", "req-7", client="acme")

    assert traced() == "ok"
    assert module.records["traceable"][0]["metadata"] == {
        "request_id": "req-7",
        "client": "acme",
    }
    plain = NullTracer().wrap(function, "agent", "chain", "req-7", client="acme")
    assert plain is function


def test_missing_langsmith_package_stops_startup():
    def loader(name):
        raise ImportError(name)

    with pytest.raises(ConfigError, match="LANGSMITH_TRACING"):
        build_tracer(load_config(TRACING_ENV), loader=loader)
