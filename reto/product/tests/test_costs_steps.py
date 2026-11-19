"""Pasos de los escenarios de features/costs.feature."""

import json

import httpx
import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from conftest import (
    GATEWAY_ENV,
    LARGE_MODEL,
    SMALL_MODEL,
    ScriptedLLM,
    build_client,
    gateway_client,
    keyed_client,
    read_log,
)
from app.main import create_app

scenarios("features/costs.feature")

QUESTION_PREFIX = "¿Quién es EMP-0004? "


def gateway_reply(status, cache_status="MISS"):
    """Crea un transporte falso que responde siempre lo mismo.

    :param status: Codigo HTTP de la respuesta del gateway
    :type status: int
    :param cache_status: Valor de ``cf-aig-cache-status``
    :type cache_status: str
    :return: Transporte de ``httpx`` sin red
    :rtype: httpx.MockTransport
    """
    body = {
        "choices": [{"message": {"content": json.dumps({"answer": "Hola"})}}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 100},
    }

    def handler(_request):
        return httpx.Response(
            status, json=body, headers={"cf-aig-cache-status": cache_status}
        )

    return httpx.MockTransport(handler)


def simulated_client(settings, directory, clock, log_stream):
    """App con los modelos simulados que arma la propia aplicacion."""
    app = create_app(
        settings=settings, directory=directory, clock=clock, log_stream=log_stream
    )
    return keyed_client(app)


@given("the product runs with the simulated models", target_fixture="client")
def product_with_simulated_models(make_settings, directory, clock, log_stream):
    """Configuracion por omision: enrutamiento encendido."""
    return simulated_client(make_settings(), directory, clock, log_stream)


@given(
    "the product runs with the simulated models and routing disabled",
    target_fixture="client",
)
def product_without_routing(make_settings, directory, clock, log_stream):
    """Linea base: todo va al modelo grande."""
    settings = make_settings(ROUTING="false")
    return simulated_client(settings, directory, clock, log_stream)


@given(
    "the product runs once with routing and once without routing",
    target_fixture="clients",
)
def product_with_and_without_routing(make_settings, directory, clock, log_stream):
    """Dos apps: una enruta al modelo pequeno y otra manda todo al grande."""
    return {
        "small": simulated_client(make_settings(), directory, clock, log_stream),
        "large": simulated_client(
            make_settings(ROUTING="false"), directory, clock, log_stream
        ),
    }


@given("a spy model that records what it receives", target_fixture="client")
def product_with_a_spy_model(make_settings, directory, clock, log_stream, request):
    """El modelo espia se usa con los dos nombres de modelo."""
    spy = ScriptedLLM(['{"answer": "ok"}'])
    request.node.spy = spy
    return build_client(
        make_settings(), spy, directory, clock=clock, log_stream=log_stream
    )


@given("a gateway that answers with status 500", target_fixture="client")
def failing_gateway(make_settings, directory, clock, log_stream):
    """Gateway que falla en cada llamada."""
    transport = gateway_reply(500)
    return gateway_client(make_settings, directory, clock, log_stream, transport)


@given("a gateway that answers from its cache", target_fixture="client")
def cached_gateway(make_settings, directory, clock, log_stream):
    """Gateway que responde desde su cache."""
    transport = gateway_reply(200, cache_status="HIT")
    return gateway_client(make_settings, directory, clock, log_stream, transport)


@when(parsers.re(r'I ask "(?P<question>[^"]*)"$'), target_fixture="response")
def ask(client, question):
    """Envia una pregunta sin historial."""
    return client.post("/ask", json={"question": question})


@when(
    parsers.re(r"I ask a question of (?P<length>\d+) characters without keywords"),
    target_fixture="response",
)
def ask_long_question(client, length):
    """Envia una pregunta simple rellenada hasta el largo pedido."""
    question = QUESTION_PREFIX + "x" * (int(length) - len(QUESTION_PREFIX))
    return client.post("/ask", json={"question": question})


@when(
    parsers.re(r'I ask "(?P<question>[^"]*)" with (?P<count>\d+) history messages'),
    target_fixture="response",
)
def ask_with_history(client, question, count, request):
    """Envia la pregunta con un historial numerado."""
    history = [
        {"role": "user" if index % 2 == 0 else "assistant", "content": f"m{index}"}
        for index in range(int(count))
    ]
    request.node.history = history
    return client.post("/ask", json={"question": question, "history": history})


@when(
    parsers.re(r'I ask "(?P<first>[^"]*)" and then "(?P<second>[^"]*)"'),
    target_fixture="answers",
)
def ask_twice(client, first, second):
    """Envia dos preguntas y devuelve ambos cuerpos."""
    return [
        client.post("/ask", json={"question": question}).json()
        for question in (first, second)
    ]


@when(
    parsers.re(r'I ask "(?P<question>[^"]*)" with the request id "(?P<rid>[^"]*)"'),
    target_fixture="response",
)
def ask_with_request_id(client, question, rid):
    """Envia la pregunta con un ``X-Request-ID`` propio."""
    return client.post(
        "/ask", json={"question": question}, headers={"X-Request-ID": rid}
    )


@when(
    parsers.re(r'I ask "(?P<question>[^"]*)" to both'),
    target_fixture="answers_by_model",
)
def ask_both(clients, question):
    """Envia la misma pregunta a las dos apps."""
    return {
        size: client.post("/ask", json={"question": question}).json()
        for size, client in clients.items()
    }


@then("the small model answer costs less than the large model answer")
def small_answer_is_cheaper(answers_by_model):
    """El modelo pequeno cuesta menos con los mismos tokens."""
    small, large = answers_by_model["small"], answers_by_model["large"]
    assert (small["model"], large["model"]) == (SMALL_MODEL, LARGE_MODEL)
    assert 0 < small["cost_usd"] < large["cost_usd"]


@then("both answers say the same")
def answers_are_equal(answers_by_model):
    """Los dos modelos simulados responden igual: la calidad no cambia."""
    small, large = answers_by_model["small"], answers_by_model["large"]
    assert small["answer"] == large["answer"]
    assert small["tools_used"] == large["tools_used"]


@then(parsers.re(r'the answer used the small model with route "(?P<route>[^"]+)"'))
def used_small_model(response, route):
    """La respuesta dice que uso el modelo pequeno y por que."""
    body = response.json()
    assert (body["model"], body["route"]) == (SMALL_MODEL, route)


@then(parsers.re(r'the answer used the large model with route "(?P<route>[^"]+)"'))
def used_large_model(response, route):
    """La respuesta dice que uso el modelo grande y por que."""
    body = response.json()
    assert (body["model"], body["route"]) == (LARGE_MODEL, route)


@then("the answer cost is above 0")
def answer_cost_is_positive(response):
    """El modelo simulado cuesta con el precio de su nombre."""
    assert response.json()["cost_usd"] > 0


@then(
    parsers.re(r"the model received only the last (?P<window>\d+) history messages")
)
def model_received_the_window(request, window):
    """Entre el prompt de sistema y la pregunta van solo los ultimos mensajes."""
    sent = request.node.spy.calls[0]
    expected = request.node.history[-int(window):]
    assert sent[1:-1] == expected
    assert sent[-1]["content"] == "¿Quién es EMP-0004?"


@then("the metrics cost is the sum of both answer costs")
def metrics_cost_is_the_sum(client, answers):
    """``/metrics`` acumula el costo de las dos respuestas."""
    total = sum(body["cost_usd"] for body in answers)
    assert total > 0
    assert client.get("/metrics").json()["cost_usd"] == pytest.approx(total)


@then(parsers.re(r"the response status is (?P<status>\d+)"))
def response_status_is(response, status):
    """Comprueba el codigo HTTP."""
    assert response.status_code == int(status)


@then(
    parsers.re(
        r'the error body says "(?P<detail>[^"]+)" and carries "(?P<rid>[^"]+)"'
    )
)
def error_body_is(response, detail, rid):
    """El error es generico y lleva el id de la peticion."""
    assert response.json() == {"detail": detail, "request_id": rid}


@then(
    parsers.re(
        r'the log has an "error" event for "(?P<rid>[^"]+)" '
        r'with type "(?P<error_type>[^"]+)"'
    )
)
def log_has_error_event(log_stream, rid, error_type):
    """El fallo del gateway queda registrado solo con su tipo, sin el token."""
    lines = [
        line
        for line in read_log(log_stream)
        if line["event"] == "error" and line["request_id"] == rid
    ]
    assert [line["error_type"] for line in lines] == [error_type]
    assert GATEWAY_ENV["CF_API_TOKEN"] not in log_stream.getvalue()


@then(parsers.re(r"the answer has (?P<count>\d+) cached call and costs 0"))
def answer_was_cached(response, count):
    """La llamada cacheada se cuenta y no suma costo."""
    body = response.json()
    assert body["cached_calls"] == int(count)
    assert body["cost_usd"] == 0
