"""Pasos pytest-bdd para los escenarios de observabilidad.

Cubre ``spec/02-observability.md``: id por peticion, log JSON con
eventos ``request``, ``agent_run``, ``audit`` y ``error``, el
endpoint ``GET /metrics`` y el ``request_id`` en la pagina web.
La hora y el log se inyectan (ver ``conftest.py``), asi que los
escenarios son deterministas.
"""

import uuid

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from tests.conftest import FailingModel

scenarios("features/observability.feature")


def _assert_is_uuid(value):
    """Verifica que el texto sea un UUID valido.

    :param value: Texto a revisar.
    :type value: str
    """
    assert str(uuid.UUID(value)) == value.lower()


# -- Given ----------------------------------------------------------

@given("the HR assistant is running", target_fixture="ctx")
def assistant_running(harness):
    """Contexto con la aplicacion estandar.

    :param harness: Arnes con cliente, log y metricas.
    :type harness: conftest.Harness
    :return: Contexto mutable del escenario.
    :rtype: dict
    """
    return {"harness": harness, "response": None}


@given(
    "the HR assistant is running with a model that fails",
    target_fixture="ctx",
)
def assistant_with_failing_model(build_harness):
    """Contexto con un modelo que siempre lanza una excepcion.

    :param build_harness: Fabrica de aplicaciones de prueba.
    :type build_harness: callable
    :return: Contexto mutable del escenario.
    :rtype: dict
    """
    return {"harness": build_harness(model=FailingModel()), "response": None}


@given(
    parsers.parse(
        "the HR assistant is running with requests that take {sec:d} seconds"
    ),
    target_fixture="ctx",
)
def assistant_with_slow_clock(build_harness, sec):
    """Contexto con un reloj en el que cada peticion tarda ``sec``.

    :param build_harness: Fabrica de aplicaciones de prueba.
    :type build_harness: callable
    :param sec: Segundos que dura cada peticion.
    :type sec: int
    :return: Contexto mutable del escenario.
    :rtype: dict
    """
    return {"harness": build_harness(tick_seconds=sec), "response": None}


# -- When -----------------------------------------------------------

@when(parsers.parse('I call GET "{path}" without a request id'))
def call_get(ctx, path):
    """Hace un GET sin encabezado ``X-Request-ID``.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param path: Ruta a consultar.
    :type path: str
    """
    ctx["response"] = ctx["harness"].client.get(path)


@when(parsers.parse('I ask "{question}" with request id "{request_id}"'))
def ask_with_request_id(ctx, question, request_id):
    """Envia una pregunta con un ``X-Request-ID`` propio.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param question: Texto de la pregunta.
    :type question: str
    :param request_id: Id que manda el cliente.
    :type request_id: str
    """
    ctx["response"] = ctx["harness"].client.post(
        "/ask",
        json={"question": question},
        headers={"X-Request-ID": request_id},
    )


@when(
    parsers.parse(
        'I ask "{question}" with a request id of {size:d} characters'
    )
)
def ask_with_long_request_id(ctx, question, size):
    """Envia una pregunta con un ``X-Request-ID`` demasiado largo.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param question: Texto de la pregunta.
    :type question: str
    :param size: Largo del id enviado.
    :type size: int
    """
    ctx["sent_id"] = "x" * size
    ctx["response"] = ctx["harness"].client.post(
        "/ask",
        json={"question": question},
        headers={"X-Request-ID": ctx["sent_id"]},
    )


@when("I send an empty question")
def ask_empty_question(ctx):
    """Envia una pregunta vacia.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    """
    ctx["response"] = ctx["harness"].client.post(
        "/ask", json={"question": ""}
    )


# -- Then: encabezado y cuerpo ---------------------------------------

@then(parsers.parse("the response status is {code:d}"))
def check_status(ctx, code):
    """Verifica el codigo HTTP.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param code: Codigo esperado.
    :type code: int
    """
    assert ctx["response"].status_code == code


@then("the response has a generated UUID in the X-Request-ID header")
def header_has_uuid(ctx):
    """Verifica que el encabezado traiga un UUID generado.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    """
    value = ctx["response"].headers["X-Request-ID"]
    _assert_is_uuid(value)
    assert value != ctx.get("sent_id")


@then(parsers.parse('the X-Request-ID header is "{expected}"'))
def header_is(ctx, expected):
    """Verifica el valor exacto del encabezado.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param expected: Valor esperado.
    :type expected: str
    """
    assert ctx["response"].headers["X-Request-ID"] == expected


@then(parsers.parse('the body request_id is "{expected}"'))
def body_request_id_is(ctx, expected):
    """Verifica el ``request_id`` del cuerpo.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param expected: Valor esperado.
    :type expected: str
    """
    assert ctx["response"].json()["request_id"] == expected


@then("the body request_id matches the X-Request-ID header")
def body_matches_header(ctx):
    """Verifica que cuerpo y encabezado lleven el mismo id.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    """
    response = ctx["response"]
    assert response.json()["request_id"] == response.headers["X-Request-ID"]


@then(parsers.parse('the body is the internal error with request id "{rid}"'))
def body_is_internal_error(ctx, rid):
    """Verifica el cuerpo exacto de la respuesta 500.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param rid: Id esperado.
    :type rid: str
    """
    assert ctx["response"].json() == {
        "detail": "internal error",
        "request_id": rid,
    }
    assert ctx["response"].headers["X-Request-ID"] == rid


# -- Then: log ------------------------------------------------------

@then(parsers.parse('the log has exactly {count:d} "{name}" event'))
def log_has_events(ctx, count, name):
    """Cuenta los eventos de un tipo en el log.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param count: Numero esperado.
    :type count: int
    :param name: Nombre del evento.
    :type name: str
    """
    assert len(ctx["harness"].events(name)) == count


@then(
    parsers.parse(
        'the log has exactly {count:d} "audit" event for tool "{tool}"'
    )
)
def log_has_audit(ctx, count, tool):
    """Verifica los eventos ``audit`` de una herramienta.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param count: Numero esperado.
    :type count: int
    :param tool: Herramienta esperada.
    :type tool: str
    """
    audits = ctx["harness"].events("audit")
    assert len(audits) == count
    assert all(a["action"] == "tool_call" for a in audits)
    assert all(a["tool"] == tool for a in audits)


@then(
    parsers.parse(
        'every log event has ts, service, event and request_id "{rid}"'
    )
)
def every_event_has_base_fields(ctx, rid):
    """Verifica los campos comunes de todas las lineas.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param rid: Id esperado en cada evento.
    :type rid: str
    """
    events = ctx["harness"].events()
    assert events
    for event in events:
        assert event["ts"]
        assert event["service"] == "hr-assistant"
        assert event["request_id"] == rid


@then(
    parsers.parse(
        "the request event reports POST /ask with status {code:d} "
        "and {latency:d} ms"
    )
)
def request_event_reports(ctx, code, latency):
    """Verifica el evento ``request`` medido con el reloj falso.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param code: Status esperado.
    :type code: int
    :param latency: Latencia esperada en ms.
    :type latency: int
    """
    (event,) = ctx["harness"].events("request")
    assert event["method"] == "POST"
    assert event["path"] == "/ask"
    assert event["status"] == code
    assert event["latency_ms"] == pytest.approx(latency)


@then(parsers.parse("the request event reports status {code:d}"))
def request_event_status(ctx, code):
    """Verifica el status y el id del evento ``request``.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param code: Status esperado.
    :type code: int
    """
    (event,) = ctx["harness"].events("request")
    assert event["status"] == code
    assert event["request_id"] == ctx["response"].headers["X-Request-ID"]


@then(parsers.parse('the log does not contain "{text}"'))
def log_does_not_contain(ctx, text):
    """Verifica que un texto no aparezca en ninguna linea del log.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param text: Texto prohibido.
    :type text: str
    """
    assert ctx["harness"].events("agent_run")
    assert text not in ctx["harness"].log_text()


@then("the log does not contain the answer text")
def log_does_not_contain_answer(ctx):
    """Verifica que ni la respuesta ni sus datos esten en el log.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    """
    log = ctx["harness"].log_text()
    assert ctx["response"].json()["answer"] not in log
    assert "Jorge Diaz" not in log


@then(
    parsers.parse(
        'the log has an error event of type "{error_type}" without the message'
    )
)
def log_has_error_type_only(ctx, error_type):
    """Verifica el evento ``error``: tipo si, mensaje no.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param error_type: Nombre de la clase de la excepcion.
    :type error_type: str
    """
    (event,) = ctx["harness"].events("error")
    assert event["error_type"] == error_type
    assert event["request_id"] == ctx["response"].headers["X-Request-ID"]
    assert FailingModel.SECRET not in ctx["harness"].log_text()
    (request,) = ctx["harness"].events("request")
    assert request["status"] == 500


# -- Then: metricas y pagina ----------------------------------------

@then(parsers.parse("the metrics report at least {count:d} request"))
def metrics_requests(ctx, count):
    """Verifica el conteo de peticiones y el pid.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param count: Minimo esperado.
    :type count: int
    """
    body = ctx["response"].json()
    assert body["requests"] >= count
    assert isinstance(body["pid"], int)
    assert body["error_rate"] == 0


@then("the metrics report p50 and p95 latency")
def metrics_latency(ctx):
    """Verifica que haya percentiles de latencia.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    """
    latency = ctx["response"].json()["latency_ms"]
    assert latency["p50"] > 0
    assert latency["p95"] >= latency["p50"]


@then("the metrics report input and output tokens above 0")
def metrics_tokens(ctx):
    """Verifica que se sumen los tokens del agente.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    """
    tokens = ctx["response"].json()["tokens"]
    assert tokens["input"] > 0
    assert tokens["output"] > 0


@then(parsers.parse("the SLO is met with target {target:d} ms"))
def slo_is_met(ctx, target):
    """Verifica que el SLO se cumpla.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param target: Meta p95 esperada.
    :type target: int
    """
    assert ctx["response"].json()["slo"] == {
        "p95_ms_target": target,
        "met": True,
    }


@then(parsers.parse("the SLO is not met with target {target:d} ms"))
def slo_is_not_met(ctx, target):
    """Verifica que el SLO no se cumpla.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param target: Meta p95 esperada.
    :type target: int
    """
    assert ctx["response"].json()["slo"] == {
        "p95_ms_target": target,
        "met": False,
    }


@then("the page shows the request_id using textContent")
def page_shows_request_id(ctx):
    """Verifica que la pagina pinte el ``request_id`` sin HTML.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    """
    html = ctx["response"].text
    assert "request_id" in html
    assert "textContent" in html
    assert "innerHTML" not in html
