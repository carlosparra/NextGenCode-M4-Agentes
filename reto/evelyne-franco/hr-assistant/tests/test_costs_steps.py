"""Pasos pytest-bdd para los escenarios de costos.

Cubre ``spec/03-costs.md``: enrutamiento por pregunta, ventana de
historial, costo por respuesta y en ``/metrics``, el 502 cuando el
gateway falla y la cache del gateway. El gateway se simula con
``httpx.MockTransport``: ningun escenario toca la red.
"""

import httpx
import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from app.config import Settings
from app.gateway import GatewayModel
from tests.conftest import RecordingModel, UnavailableModel

scenarios("features/costs.feature")


def _cache_hit(_request):
    """Respuesta del gateway que viene de su cache.

    :param _request: Peticion recibida (ignorada).
    :type _request: httpx.Request
    :return: Respuesta valida con ``cf-aig-cache-status: HIT``.
    :rtype: httpx.Response
    """
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": '{"answer": "Desde la cache"}'}}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 5},
        },
        headers={"cf-aig-cache-status": "HIT"},
    )


def _cached_gateway(name):
    """Crea un ``GatewayModel`` cuyo gateway siempre responde HIT.

    :param name: Nombre del modelo.
    :type name: str
    :return: Modelo con cliente simulado.
    :rtype: app.gateway.GatewayModel
    """
    settings = Settings(
        cf_account_id="acc-123",
        cf_gateway_id="gw-456",
        cf_api_token="cf-token-test",
        cache_ttl_seconds=60,
    )
    client = httpx.Client(transport=httpx.MockTransport(_cache_hit))
    return GatewayModel(name=name, settings=settings, client=client)


def _context(harness):
    """Crea el contexto mutable de un escenario.

    :param harness: Arnes de la aplicacion.
    :type harness: conftest.Harness
    :return: Contexto con el arnes y las respuestas.
    :rtype: dict
    """
    return {"harness": harness, "response": None, "answers": []}


# -- Given ----------------------------------------------------------

@given("the HR assistant is running", target_fixture="ctx")
def assistant_running(harness):
    """Contexto con la aplicacion estandar y los dos modelos simulados.

    :param harness: Arnes con cliente, log y metricas.
    :type harness: conftest.Harness
    :return: Contexto del escenario.
    :rtype: dict
    """
    return _context(harness)


@given("the HR assistant is running with routing off", target_fixture="ctx")
def assistant_without_routing(build_harness):
    """Contexto con ``ROUTING=false``.

    :param build_harness: Fabrica de aplicaciones de prueba.
    :type build_harness: callable
    :return: Contexto del escenario.
    :rtype: dict
    """
    return _context(build_harness(routing=False))


@given(
    parsers.parse("the HR assistant is running with a history window of {size:d}"),
    target_fixture="ctx",
)
def assistant_with_window(build_harness, size):
    """Contexto con ``HISTORY_WINDOW`` y modelos que anotan sus mensajes.

    :param build_harness: Fabrica de aplicaciones de prueba.
    :type build_harness: callable
    :param size: Mensajes de historial que se mandan.
    :type size: int
    :return: Contexto del escenario.
    :rtype: dict
    """
    harness = build_harness(history_window=size, model_factory=RecordingModel)
    return _context(harness)


@given(
    "the HR assistant is running with a gateway that is down",
    target_fixture="ctx",
)
def assistant_with_gateway_down(build_harness):
    """Contexto con modelos que lanzan ``ModelUnavailable``.

    :param build_harness: Fabrica de aplicaciones de prueba.
    :type build_harness: callable
    :return: Contexto del escenario.
    :rtype: dict
    """
    return _context(build_harness(model_factory=UnavailableModel))


@given(
    "the HR assistant is running with a gateway whose cache answers HIT",
    target_fixture="ctx",
)
def assistant_with_cached_gateway(build_harness):
    """Contexto con modelos del gateway cuya cache siempre acierta.

    :param build_harness: Fabrica de aplicaciones de prueba.
    :type build_harness: callable
    :return: Contexto del escenario.
    :rtype: dict
    """
    return _context(build_harness(model_factory=_cached_gateway))


# -- When -----------------------------------------------------------

@when(parsers.parse('I ask "{question}"'))
def ask(ctx, question):
    """Envia una pregunta y guarda la respuesta.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param question: Texto de la pregunta.
    :type question: str
    """
    ctx["response"] = ctx["harness"].client.post("/ask", json={"question": question})
    ctx["answers"].append(ctx["response"])


@when(parsers.parse('I ask "{question}" with request id {request_id}'))
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


@when(parsers.parse('I ask "{question}" with a history of {size:d} messages'))
def ask_with_history(ctx, question, size):
    """Envia una pregunta con un historial de ``size`` mensajes.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param question: Texto de la pregunta.
    :type question: str
    :param size: Mensajes del historial.
    :type size: int
    """
    roles = ("user", "assistant")
    history = [
        {"role": roles[i % 2], "content": f"mensaje {i}"} for i in range(size)
    ]
    ctx["question"] = question
    ctx["history"] = history
    ctx["response"] = ctx["harness"].client.post(
        "/ask", json={"question": question, "history": history}
    )


@when(parsers.parse('I call GET "{path}"'))
def call_get(ctx, path):
    """Hace un GET a la ruta indicada.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param path: Ruta a consultar.
    :type path: str
    """
    ctx["response"] = ctx["harness"].client.get(path)


# -- Then -----------------------------------------------------------

@then(parsers.parse("the response status is {code:d}"))
def check_status(ctx, code):
    """Verifica el codigo HTTP.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param code: Codigo esperado.
    :type code: int
    """
    assert ctx["response"].status_code == code


@then(parsers.parse('the answer used the {size} model because of "{reason}"'))
def answer_used_model(ctx, size, reason):
    """Verifica el modelo elegido y el motivo del enrutador.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param size: ``small`` o ``large``.
    :type size: str
    :param reason: Motivo esperado en ``route``.
    :type reason: str
    """
    settings = ctx["harness"].settings
    expected = {"small": settings.model_small, "large": settings.model_large}
    body = ctx["response"].json()
    assert body["model"] == expected[size]
    assert body["route"] == reason


@then("the cost is above 0")
def cost_is_positive(ctx):
    """Verifica que la respuesta tenga costo y no se redondee a 0.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    """
    body = ctx["response"].json()
    assert body["cost_usd"] > 0
    assert body["cached_calls"] == 0


@then(
    parsers.parse(
        "the model received the last {size:d} history messages plus the question"
    )
)
def model_received_window(ctx, size):
    """Verifica lo que recibio el modelo en su primera llamada.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param size: Mensajes de historial esperados.
    :type size: int
    """
    harness = ctx["harness"]
    model = harness.models[harness.settings.model_small]
    first_call = model.calls[0]
    assert len(first_call) == size + 1
    assert first_call[:size] == ctx["history"][-size:]
    assert first_call[-1] == {"role": "user", "content": ctx["question"]}


@then("the metrics cost is the sum of both answers")
def metrics_cost_is_sum(ctx):
    """Verifica que ``/metrics`` acumule el costo de las respuestas.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    """
    costs = [answer.json()["cost_usd"] for answer in ctx["answers"]]
    assert len(costs) == 2
    assert all(cost > 0 for cost in costs)
    assert ctx["response"].json()["cost_usd"] == pytest.approx(sum(costs))


@then(
    parsers.parse(
        'the body is the model unavailable error with request id "{rid}"'
    )
)
def body_is_model_unavailable(ctx, rid):
    """Verifica el cuerpo exacto de la respuesta 502.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param rid: Id esperado.
    :type rid: str
    """
    assert ctx["response"].json() == {
        "detail": "model unavailable",
        "request_id": rid,
    }
    assert ctx["response"].headers["X-Request-ID"] == rid


@then(
    parsers.parse(
        'the log has an error event of type "{error_type}" without the message'
    )
)
def log_has_error_type_only(ctx, error_type):
    """Verifica el evento ``error``: tipo si, mensaje no, status 502.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param error_type: Nombre de la clase de la excepcion.
    :type error_type: str
    """
    harness = ctx["harness"]
    (event,) = harness.events("error")
    assert event["error_type"] == error_type
    assert event["request_id"] == ctx["response"].headers["X-Request-ID"]
    assert UnavailableModel.SECRET not in harness.log_text()
    (request,) = harness.events("request")
    assert request["status"] == 502


@then(
    parsers.parse(
        "the answer has {count:d} cached call and a cost of 0"
    )
)
def answer_is_cached(ctx, count):
    """Verifica que la llamada cacheada se cuente y no cueste.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param count: Llamadas cacheadas esperadas.
    :type count: int
    """
    body = ctx["response"].json()
    assert body["cached_calls"] == count
    assert body["cost_usd"] == 0
    assert body["answer"]
