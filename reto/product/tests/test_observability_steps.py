"""Pasos de los escenarios de features/observability.feature."""

import uuid

from pytest_bdd import given, parsers, scenarios, then, when

from conftest import FakeClock, build_client, read_log

scenarios("features/observability.feature")

QUESTION_PATTERN = r'I ask "(?P<question>[^"]*)"'


class FailingLLM:  # pylint: disable=too-few-public-methods
    """Modelo doble que siempre lanza una excepcion con un mensaje sensible."""

    def complete(self, messages):
        """Lanza siempre ``RuntimeError``.

        :param messages: Conversacion enviada por el agente
        :type messages: list[dict]
        :raises RuntimeError: Siempre, con un texto que no debe llegar al log
        """
        raise RuntimeError(f"secret detail with {len(messages)} messages")


def events_named(log_stream, event, request_id):
    """Filtra los eventos del log por nombre y ``request_id``."""
    return [
        line
        for line in read_log(log_stream)
        if line["event"] == event and line["request_id"] == request_id
    ]


@given("a model that fails with a secret message", target_fixture="client")
def client_with_a_failing_model(settings, directory, clock, log_stream):
    """App con un modelo que truena; el 500 lo devuelve la propia app."""
    return build_client(
        settings,
        FailingLLM(),
        directory,
        clock=clock,
        log_stream=log_stream,
        raise_server_exceptions=False,
    )


@given(
    parsers.re(r"a clock that advances (?P<seconds>\d+) seconds per reading"),
    target_fixture="client",
)
def client_with_a_slow_clock(seconds, settings, fake_llm, directory, log_stream):
    """App con un reloj que hace que cada peticion tarde ``seconds``."""
    slow_clock = FakeClock(step_seconds=float(seconds))
    return build_client(
        settings, fake_llm, directory, clock=slow_clock, log_stream=log_stream
    )


@when("I call the health check without a request id", target_fixture="response")
def call_health_without_request_id(client):
    """Llama a ``/health`` sin encabezado."""
    return client.get("/health")


@when(
    parsers.re(
        r"I call the health check with a request id of (?P<length>\d+) characters"
    ),
    target_fixture="response",
)
def call_health_with_a_long_request_id(client, length):
    """Llama a ``/health`` con un id demasiado largo."""
    return client.get("/health", headers={"X-Request-ID": "x" * int(length)})


@when(
    parsers.re(QUESTION_PATTERN + r' with the request id "(?P<request_id>[^"]*)"$'),
    target_fixture="response",
)
def ask_with_request_id(client, question, request_id):
    """Envia la pregunta con un ``X-Request-ID`` propio."""
    return client.post(
        "/ask", json={"question": question}, headers={"X-Request-ID": request_id}
    )


@when(
    parsers.re(QUESTION_PATTERN + r" (?P<count>\d+) times?$"),
    target_fixture="response",
)
def ask_several_times(client, question, count):
    """Envia la misma pregunta varias veces y devuelve la ultima respuesta."""
    responses = [
        client.post("/ask", json={"question": question}) for _ in range(int(count))
    ]
    return responses[-1]


@then("the response carries a new UUID request id")
def response_carries_a_uuid(response):
    """El encabezado trae un UUID valido generado por la app."""
    assert uuid.UUID(response.headers["X-Request-ID"])


@then(parsers.re(r'the response header request id is "(?P<request_id>[^"]*)"'))
def header_request_id_is(response, request_id):
    """El encabezado devuelve el id indicado."""
    assert response.headers["X-Request-ID"] == request_id


@then(parsers.re(r'the response body request id is "(?P<request_id>[^"]*)"'))
def body_request_id_is(response, request_id):
    """El cuerpo de ``/ask`` devuelve el id indicado."""
    assert response.json()["request_id"] == request_id


@then(parsers.re(r"the response status is (?P<status>\d+)"))
def response_status_is(response, status):
    """Comprueba el codigo HTTP."""
    assert response.status_code == int(status)


@then(parsers.re(r'the error body is generic and carries "(?P<request_id>[^"]*)"'))
def error_body_is_generic(response, request_id):
    """El 500 no expone detalles y lleva el id."""
    assert response.json() == {"detail": "internal error", "request_id": request_id}
    assert response.headers["X-Request-ID"] == request_id


@then(parsers.re(r'the log has a "request" event for "(?P<rid>[^"]+)"$'))
def log_has_request_event(log_stream, rid):
    """La peticion HTTP queda registrada una vez con su latencia."""
    lines = events_named(log_stream, "request", rid)
    assert len(lines) == 1
    assert lines[0]["latency_ms"] >= 0
    assert lines[0]["method"] == "POST"
    assert lines[0]["path"] == "/ask"
    assert lines[0]["status"] == 200


@then(
    parsers.re(
        r'the log has an "audit" event for "(?P<rid>[^"]+)" '
        r'with tool "(?P<tool>[^"]+)"'
    )
)
def log_has_audit_event(log_stream, rid, tool):
    """La herramienta llamada queda auditada con sus argumentos."""
    lines = events_named(log_stream, "audit", rid)
    assert len(lines) == 1
    assert lines[0]["action"] == "tool_call"
    assert lines[0]["tool"] == tool
    assert lines[0]["args"] == {"employee_id": "EMP-0004"}


@then(
    parsers.re(
        r'the log has an "agent_run" event for "(?P<rid>[^"]+)" '
        r'that stopped with "(?P<stopped>[^"]+)"'
    )
)
def log_has_agent_run_event(log_stream, rid, stopped):
    """La corrida del agente se resume solo con conteos."""
    lines = events_named(log_stream, "agent_run", rid)
    assert len(lines) == 1
    run = lines[0]
    assert run["stopped"] == stopped
    assert run["question_chars"] == len("¿Quién es EMP-0004?")
    assert run["history_messages"] == 0
    assert run["steps"] == 2
    assert run["tools"] == ["get_employee"]
    assert run["input_tokens"] > 0
    assert run["output_tokens"] > 0


@then(
    parsers.re(
        r'the log has an "error" event for "(?P<rid>[^"]+)" '
        r'with type "(?P<error_type>[^"]+)"'
    )
)
def log_has_error_event(log_stream, rid, error_type):
    """El error queda registrado solo con su tipo."""
    lines = events_named(log_stream, "error", rid)
    assert len(lines) == 1
    assert lines[0]["error_type"] == error_type


@then(parsers.re(r'no log line contains "(?P<text>[^"]+)"'))
def no_log_line_contains(log_stream, text):
    """El texto no aparece en ninguna linea del log."""
    assert read_log(log_stream)
    assert text not in log_stream.getvalue()


@then("the metrics report an error rate above 0")
def metrics_report_errors(client):
    """La tasa de error refleja el 500."""
    assert client.get("/metrics").json()["error_rate"] > 0


@then(parsers.re(r"the metrics count (?P<count>\d+) requests"))
def metrics_count_requests(client, count):
    """Cuenta las peticiones atendidas, sin contar ``/metrics``."""
    assert client.get("/metrics").json()["requests"] == int(count)


@then("the metrics report input tokens above 0")
def metrics_report_tokens(client):
    """Los tokens de las respuestas se suman."""
    tokens = client.get("/metrics").json()["tokens"]
    assert tokens["input"] > 0
    assert tokens["output"] > 0


@then("the metrics report the p50 and p95 latency")
def metrics_report_latency(client):
    """La latencia trae los dos percentiles."""
    latency = client.get("/metrics").json()["latency_ms"]
    assert set(latency) == {"p50", "p95"}
    assert 0 < latency["p50"] <= latency["p95"]


@then("the SLO is met")
def slo_is_met(client, settings):
    """El p95 queda por debajo de la meta."""
    slo = client.get("/metrics").json()["slo"]
    assert slo == {"p95_ms_target": settings.slo_p95_ms, "met": True}


@then("the SLO is not met")
def slo_is_not_met(client):
    """El p95 supera la meta."""
    assert client.get("/metrics").json()["slo"]["met"] is False
