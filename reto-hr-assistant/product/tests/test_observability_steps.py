"""Pasos de los escenarios de observabilidad (``features/observability.feature``)."""

import sys
import uuid
from datetime import datetime, timedelta

from pytest_bdd import given, parsers, scenarios, then, when

scenarios("features/observability.feature")

DEFAULT_QUESTION = "¿Quién es EMP-0004?"


class FailingModel:
    """Modelo que siempre truena con un mensaje que no debe llegar al log.

    :param message: Mensaje del error
    :type message: str
    """

    def __init__(self, message):
        self._message = message

    def complete(self, messages):
        """Lanza siempre un ``RuntimeError``.

        :param messages: Conversación recibida
        :type messages: list[dict]
        :raises RuntimeError: Siempre
        """
        raise RuntimeError(self._message)


def is_uuid4(value):
    """Indica si un texto es un UUID versión 4.

    :param value: Texto a revisar
    :type value: str
    :return: ``True`` si es un UUID4
    :rtype: bool
    """
    try:
        return uuid.UUID(value).version == 4
    except (TypeError, ValueError):
        return False


# --- Given ---------------------------------------------------------------


@given(
    parsers.parse('the assistant is running as service "{service}"'),
    target_fixture="observed",
)
def running_as_service(make_observed, service):
    """Arranca la aplicación con un nombre de servicio propio."""
    return make_observed({"SERVICE_NAME": service})


@given(
    parsers.parse("the assistant is running with at most {steps:d} agent step"),
    target_fixture="observed",
)
def running_with_step_cap(make_observed, steps):
    """Arranca la aplicación con el tope de vueltas indicado."""
    return make_observed({"AGENT_MAX_STEPS": str(steps)})


@given(
    parsers.parse('the assistant is running with a model that fails with "{message}"'),
    target_fixture="observed",
)
def running_with_failing_model(make_observed, message):
    """Arranca la aplicación con un modelo que siempre falla."""
    return make_observed(model=FailingModel(message))


@given(
    parsers.parse(
        "the assistant is running with a clock that takes {seconds:d} seconds "
        "per request"
    ),
    target_fixture="observed",
)
def running_with_slow_clock(make_observed, make_clock, seconds):
    """Arranca la aplicación con un reloj que avanza muchos segundos por lectura."""
    return make_observed(clock=make_clock(step_seconds=float(seconds)))


@given(
    "LangSmith tracing is on but there is no API key",
    target_fixture="observed",
)
def tracing_without_key(make_observed, monkeypatch):
    """Enciende el tracing sin clave y hace fallar cualquier ``import langsmith``."""
    monkeypatch.setitem(sys.modules, "langsmith", None)
    return make_observed({"LANGSMITH_TRACING": "true"})


# --- When ----------------------------------------------------------------


@when("I call every endpoint without a request id", target_fixture="responses")
def call_every_endpoint(observed):
    """Llama a cada ruta sin encabezado, incluida una pregunta inválida."""
    client = observed.client
    return [
        client.get("/health"),
        client.get("/metrics"),
        client.post("/ask", json={"question": DEFAULT_QUESTION}),
        client.post("/ask", json={}),
    ]


@when(
    parsers.parse('I ask "{question}" with the request id "{request_id}"'),
    target_fixture="exchange",
)
def ask_with_request_id(observed, question, request_id):
    """Manda una pregunta con el encabezado ``X-Request-ID``."""
    response = observed.client.post(
        "/ask", json={"question": question}, headers={"X-Request-ID": request_id}
    )
    return {"question": question, "response": response}


@when(parsers.parse("I ask {count:d} questions"))
def ask_several_questions(observed, count):
    """Manda varias preguntas válidas sin encabezado."""
    for _ in range(count):
        response = observed.client.post("/ask", json={"question": DEFAULT_QUESTION})
        assert response.status_code == 200


@when("I read the metrics", target_fixture="metrics")
def read_metrics(observed):
    """Lee ``GET /metrics``."""
    response = observed.client.get("/metrics")
    assert response.status_code == 200
    return response.json()


@when("I open the home page", target_fixture="page")
def open_home_page(observed):
    """Descarga la página web."""
    response = observed.client.get("/")
    assert response.status_code == 200
    return response.text


# --- Then: request id ----------------------------------------------------


@then("every response has a UUID in the X-Request-ID header")
def every_response_has_uuid(responses):
    """Revisa el encabezado de todas las respuestas, incluida la 422."""
    assert [response.status_code for response in responses] == [200, 200, 200, 422]
    for response in responses:
        assert is_uuid4(response.headers.get("X-Request-ID"))


@then(parsers.parse('the X-Request-ID header is "{expected}"'))
def header_is(exchange, expected):
    """Compara el encabezado con el valor esperado."""
    assert exchange["response"].headers["X-Request-ID"] == expected


@then("the X-Request-ID header is a UUID")
def header_is_uuid(exchange):
    """Revisa que el encabezado sea un UUID generado."""
    assert is_uuid4(exchange["response"].headers["X-Request-ID"])


@then("the body request_id matches the X-Request-ID header")
def body_matches_header(exchange):
    """El cuerpo y el encabezado llevan el mismo id."""
    response = exchange["response"]
    assert response.status_code == 200
    assert response.json()["request_id"] == response.headers["X-Request-ID"]


# --- Then: log -----------------------------------------------------------


@then(parsers.parse('the log has exactly {count:d} "{name}" event'))
def log_has_events(observed, count, name):
    """Cuenta los eventos de un tipo."""
    assert len(observed.events(name)) == count


@then(
    parsers.parse(
        'every log line has request id "{request_id}", a UTC timestamp '
        'and service "{service}"'
    )
)
def every_line_has_base_fields(observed, request_id, service):
    """Cada línea lleva el mismo id, la hora del reloj falso en UTC y el servicio."""
    events = observed.events()
    assert events
    for event in events:
        assert event["request_id"] == request_id
        assert event["service"] == service
        timestamp = datetime.fromisoformat(event["ts"])
        assert timestamp.utcoffset() == timedelta(0)
        assert timestamp.isoformat().startswith("2026-01-15T09:30")


@then(
    parsers.parse(
        'the audit event records the tool "{tool}" with employee_id "{employee_id}"'
    )
)
def audit_records_tool(observed, tool, employee_id):
    """La auditoría trae la acción, la herramienta y sus argumentos."""
    (audit,) = observed.events("audit")
    assert audit["action"] == "tool_call"
    assert audit["tool"] == tool
    assert audit["args"] == {"employee_id": employee_id}


@then(
    parsers.parse(
        "the request event records POST /ask with status {status:d} and a latency"
    )
)
def request_event_recorded(observed, status):
    """El evento ``request`` describe la petición HTTP."""
    (request,) = observed.events("request")
    assert request["method"] == "POST"
    assert request["path"] == "/ask"
    assert request["status"] == status
    assert isinstance(request["latency_ms"], (int, float))
    assert request["latency_ms"] >= 0


@then("the log does not contain the question")
def log_without_question(observed, exchange):
    """El texto de la pregunta no aparece en ninguna línea."""
    assert observed.events("agent_run")
    assert exchange["question"] not in observed.log_text()


@then("the log does not contain the answer")
def log_without_answer(observed, exchange):
    """El texto de la respuesta no aparece en ninguna línea."""
    answer = exchange["response"].json()["answer"]
    assert answer
    assert answer not in observed.log_text()


@then(
    parsers.parse(
        'the agent_run event says it stopped at "{stopped}" after {steps:d} step'
    )
)
def agent_run_stopped(observed, stopped, steps):
    """El evento ``agent_run`` explica por qué terminó el agente."""
    (run,) = observed.events("agent_run")
    assert run["stopped"] == stopped
    assert run["steps"] == steps
    assert run["tools"] == ["get_employee"]
    assert run["input_tokens"] > 0
    assert run["output_tokens"] > 0


@then(
    parsers.parse(
        "the agent_run event counts the question characters and "
        "{history:d} history messages"
    )
)
def agent_run_counts(observed, exchange, history):
    """El evento ``agent_run`` lleva números, no textos."""
    (run,) = observed.events("agent_run")
    assert run["question_chars"] == len(exchange["question"])
    assert run["history_messages"] == history


@then("the response is a 500 internal error that includes the request id")
def response_is_internal_error(exchange):
    """La respuesta de error es genérica y trae el id."""
    response = exchange["response"]
    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "boom-1"
    assert response.json() == {"detail": "internal error", "request_id": "boom-1"}


@then(
    parsers.parse(
        'the log has an error event of type "{error_type}" without the message'
    )
)
def error_event_logged(observed, error_type):
    """El evento ``error`` trae el tipo pero nunca el mensaje."""
    (error,) = observed.events("error")
    assert error["request_id"] == "boom-1"
    assert error_type in error.values()
    assert "secret failure detail" not in observed.log_text()


# --- Then: metricas, tracing y pagina ------------------------------------


@then(parsers.parse("the metrics count {count:d} requests with no errors"))
def metrics_count_requests(metrics, count):
    """Cuenta las peticiones previas a la lectura de métricas."""
    assert isinstance(metrics["pid"], int)
    assert metrics["requests"] == count
    assert metrics["error_rate"] == 0.0


@then("the metrics report input and output tokens")
def metrics_report_tokens(metrics):
    """Los tokens de las dos preguntas quedan sumados."""
    assert metrics["tokens"]["input"] > 0
    assert metrics["tokens"]["output"] > 0


@then(
    parsers.parse(
        "the metrics report p50 and p95 latencies within the SLO of {target:d} ms"
    )
)
def metrics_within_slo(metrics, target):
    """Con el reloj rápido el p95 queda por debajo de la meta."""
    latency = metrics["latency_ms"]
    assert 0 <= latency["p50"] <= latency["p95"] < target
    assert metrics["slo"] == {"p95_ms_target": target, "met": True}


@then("the metrics say the SLO is not met")
def metrics_slo_not_met(metrics):
    """Con el reloj lento el p95 supera la meta."""
    assert metrics["latency_ms"]["p95"] >= metrics["slo"]["p95_ms_target"]
    assert metrics["slo"]["met"] is False


@then("the response is a normal answer")
def response_is_normal(exchange):
    """Sin clave, la respuesta es la misma que sin tracing."""
    response = exchange["response"]
    assert response.status_code == 200
    assert "Jorge Díaz" in response.json()["answer"]


@then("the page has an element for the request id")
def page_has_request_id(page):
    """La página reserva un lugar para el id y lo lee de la respuesta."""
    assert 'data-testid="request-id"' in page
    assert "request_id" in page
