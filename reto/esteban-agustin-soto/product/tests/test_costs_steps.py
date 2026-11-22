"""Step definitions for features/costs.feature."""

import httpx
import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from conftest import gateway_reply

scenarios("features/costs.feature")


@pytest.fixture(name="world")
def world_fixture():
    """Bolsa mutable con la preparación del escenario y las respuestas hasta ahora.

    :return: Diccionario del escenario.
    :rtype: dict
    """
    return {"env": {}, "handler": None, "client": None, "stream": None,
            "responses": []}


def _client(world, make_costs_client):
    """Build the client once, with the setup gathered so far."""
    if world["client"] is None:
        world["client"], world["stream"] = make_costs_client(
            env=world["env"], handler=world["handler"]
        )
    return world["client"]


@given("the app uses the fake models")
def _fake_models(world):
    world["env"]["MODEL_PROVIDER"] = "fake"


@given("routing is off")
def _routing_off(world):
    world["env"]["ROUTING"] = "false"


@given("the gateway answers with a cache HIT")
def _gateway_hit(world):
    world["handler"] = lambda request: gateway_reply(cache_status="HIT")


@given("the gateway answers normally")
def _gateway_ok(world):
    world["env"]["CF_API_TOKEN"] = "s3cret-token-value"
    world["handler"] = lambda request: gateway_reply()


@given(parsers.parse("the gateway fails with status {status:d}"))
def _gateway_fails(world, status):
    world["handler"] = lambda request: httpx.Response(status, text="boom")


@when(parsers.parse('the user asks "{question}"'))
def _ask(world, make_costs_client, question):
    client = _client(world, make_costs_client)
    world["responses"].append(client.post("/ask", json={"question": question}))


@then(parsers.parse('the response uses the model "{model}" with route "{route}"'))
def _model_and_route(world, model, route):
    body = world["responses"][-1].json()
    assert body["model"] == model
    assert body["route"] == route


@then("the cost of the response is greater than zero")
def _cost_positive(world):
    assert world["responses"][-1].json()["cost_usd"] > 0


@then(parsers.parse("the cost of the response is {value:d}"))
def _cost_exact(world, value):
    assert world["responses"][-1].json()["cost_usd"] == value


@then(parsers.parse("the response has {count:d} cached call"))
def _cached_calls(world, count):
    assert world["responses"][-1].json()["cached_calls"] == count


@then(parsers.parse("the status is {status:d}"))
def _status(world, status):
    assert world["responses"][-1].status_code == status


@then('the detail is "model unavailable" and a request id is present')
def _detail_and_id(world):
    body = world["responses"][-1].json()
    assert body["detail"] == "model unavailable"
    assert body["request_id"]


@then("neither the log nor the metrics contain the token")
def _token_hidden(world):
    assert world["responses"][-1].status_code == 200
    metrics = world["client"].get("/metrics").text
    assert "s3cret-token-value" not in world["stream"].getvalue()
    assert "s3cret-token-value" not in metrics


@then("the metrics cost equals the sum of the response costs")
def _metrics_sum(world):
    total = sum(r.json()["cost_usd"] for r in world["responses"])
    reported = world["client"].get("/metrics").json()["cost_usd"]
    assert total > 0
    assert reported == pytest.approx(total)
