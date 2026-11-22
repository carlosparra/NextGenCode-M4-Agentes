"""Step definitions for features/observability.feature."""

import uuid
from datetime import datetime, timedelta

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from conftest import FakeClock, log_lines

scenarios("features/observability.feature")


class CrashingModel:
    """Model double that always fails with a given message."""

    def __init__(self, message):
        self.message = message

    def complete(self, messages):
        """Lanza un error en lugar de responder.

        :param messages: Mensajes que recibe el modelo.
        :type messages: list
        :raises RuntimeError: Siempre, con el mensaje configurado.
        """
        raise RuntimeError(self.message)


@pytest.fixture(name="world")
def world_fixture():
    """Bolsa mutable con la preparación del escenario y la última respuesta.

    :return: Diccionario del escenario.
    :rtype: dict
    """
    return {"model": None, "env": {}, "clock": None, "headers": {},
            "client": None, "stream": None, "response": None}


def _client(world, make_observed_client):
    """Build the client once, with the setup gathered so far."""
    if world["client"] is None:
        world["client"], world["stream"] = make_observed_client(
            model=world["model"], env=world["env"], clock=world["clock"]
        )
    return world["client"]


@given(parsers.parse('the client sends the request id "{value}"'))
def _send_id(world, value):
    world["headers"] = {"X-Request-ID": value}


@given(parsers.parse('a model that crashes with the message "{message}"'))
def _crashing_model(world, message):
    world["model"] = CrashingModel(message)


@given(parsers.parse("a clock that advances {millis:d} milliseconds per reading"))
def _slow_clock(world, millis):
    world["clock"] = FakeClock(step_ms=millis)


@given(parsers.parse("the SLO target is {millis:d} milliseconds"))
def _slo_target(world, millis):
    world["env"]["SLO_P95_MS"] = str(millis)


@given("there is no LangSmith key")
def _no_key(monkeypatch):
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)


@given("the tracing library fails if it is used")
def _tracing_fails(monkeypatch):
    def explode(*_args, **_kwargs):
        raise AssertionError("langsmith must not be used without a key")

    monkeypatch.setattr("app.tracing.traceable", explode)


@when(parsers.re(r'I ask "(?P<question>.*)"'))
def _ask(world, make_observed_client, question):
    client = _client(world, make_observed_client)
    world["response"] = client.post(
        "/ask", json={"question": question}, headers=world["headers"]
    )


@when("I request the health endpoint")
def _health(world, make_observed_client):
    client = _client(world, make_observed_client)
    world["response"] = client.get("/health", headers=world["headers"])


@when("I request the metrics")
def _metrics(world, make_observed_client):
    client = _client(world, make_observed_client)
    world["response"] = client.get("/metrics")


@when("I open the web page")
def _page(world, make_observed_client):
    client = _client(world, make_observed_client)
    world["response"] = client.get("/")


@then(parsers.parse("the response status is {status:d}"))
def _status(world, status):
    assert world["response"].status_code == status


@then("the X-Request-ID header is a UUID")
def _header_is_uuid(world):
    uuid.UUID(world["response"].headers["X-Request-ID"])


@then(parsers.parse('the X-Request-ID header is "{value}"'))
def _header_is(world, value):
    assert world["response"].headers["X-Request-ID"] == value


@then("the body request_id equals the header")
def _body_matches_header(world):
    header = world["response"].headers["X-Request-ID"]
    assert world["response"].json()["request_id"] == header


@then(parsers.parse('every log line has the request id "{value}"'))
def _log_has_id(world, value):
    lines = log_lines(world["stream"])
    assert lines
    assert {line["request_id"] for line in lines} == {value}


@then(parsers.parse('the log has the events "{names}"'))
def _log_events(world, names):
    seen = {line["event"] for line in log_lines(world["stream"])}
    assert set(names.split(", ")) <= seen


@then("all log lines share one request id")
def _one_request_id(world):
    ids = {line["request_id"] for line in log_lines(world["stream"])}
    assert len(ids) == 1
    assert ids == {world["response"].headers["X-Request-ID"]}


@then("all log timestamps are ISO 8601 in UTC")
def _timestamps_utc(world):
    for line in log_lines(world["stream"]):
        stamp = datetime.fromisoformat(line["ts"].replace("Z", "+00:00"))
        assert stamp.utcoffset() == timedelta(0)


@then(parsers.parse('the log does not contain "{text}"'))
def _log_omits(world, text):
    assert text not in world["stream"].getvalue()


@then(parsers.parse('the body is "{detail}" with the request id'))
def _error_body(world, detail):
    body = world["response"].json()
    assert body == {
        "detail": detail,
        "request_id": world["response"].headers["X-Request-ID"],
    }


@then(parsers.parse('the log has an error event of type "{kind}"'))
def _error_event(world, kind):
    errors = [line for line in log_lines(world["stream"])
              if line["event"] == "error"]
    assert len(errors) == 1
    assert errors[0]["error_type"] == kind


@then(parsers.parse("the metrics show at least {count:d} requests"))
def _metrics_requests(world, count):
    assert world["response"].json()["requests"] >= count


@then("the metrics have latency, token and SLO figures")
def _metrics_fields(world):
    body = world["response"].json()
    assert isinstance(body["pid"], int)
    assert 0 <= body["error_rate"] <= 1
    assert set(body["latency_ms"]) == {"p50", "p95"}
    assert body["tokens"]["input"] > 0
    assert body["tokens"]["output"] > 0
    assert set(body["slo"]) == {"p95_ms_target", "met"}


@then("the SLO is met")
def _slo_met(world):
    assert world["response"].json()["slo"]["met"] is True


@then("the SLO is not met")
def _slo_not_met(world):
    slo = world["response"].json()["slo"]
    assert slo["p95_ms_target"] == 2000
    assert slo["met"] is False


@then("the page has the request id slot")
def _page_slot(world):
    assert 'data-testid="request-id"' in world["response"].text


@then("the page does not use innerHTML")
def _page_safe(world):
    assert "innerHTML" not in world["response"].text
