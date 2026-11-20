"""Pruebas unitarias de los modelos (``FakeModel`` y ``GatewayModel``)."""

import json

import httpx
import pytest

from conftest import (
    GATEWAY_ENV,
    GATEWAY_URL,
    LARGE_MODEL,
    SMALL_MODEL,
    gateway_http_client,
    gateway_response,
)

from app.config import load_config
from app.llm import FakeModel, GatewayModel, ModelUnavailableError, build_models

DEPARTMENTS = ["Tecnología", "Ventas", "Finanzas"]
PREFIX = "Resultado de la herramienta: "
QUESTION = [{"role": "user", "content": "¿Quién es EMP-0001?"}]


@pytest.fixture
def fake_model():
    """Modelo simulado con los departamentos de los datos."""
    return FakeModel(SMALL_MODEL, DEPARTMENTS)


def _gateway(handler, extra_environ=None):
    """Crea un ``GatewayModel`` pequeño que habla con ``handler``."""
    config = load_config({**GATEWAY_ENV, **(extra_environ or {})})
    return GatewayModel(SMALL_MODEL, config, gateway_http_client(handler))


def _decide(model, content):
    """Pide al modelo una respuesta para un único mensaje del usuario."""
    reply = model.complete([{"role": "user", "content": content}])
    return json.loads(reply.text)


def test_tool_result_wins_over_employee_id(fake_model):
    decision = _decide(fake_model, PREFIX + "EMP-0004 Jorge Díaz")

    assert decision == {"answer": "Según el directorio: EMP-0004 Jorge Díaz"}


def test_employee_id_asks_for_get_employee(fake_model):
    decision = _decide(fake_model, "¿Quién es EMP-0002?")

    assert decision == {"tool": "get_employee", "args": {"employee_id": "EMP-0002"}}


def test_known_department_asks_for_search_by_department(fake_model):
    decision = _decide(fake_model, "¿Quiénes están en Ventas?")

    assert decision == {
        "tool": "search_by_department",
        "args": {"department": "Ventas"},
    }


def test_question_without_entity_gets_help(fake_model):
    decision = _decide(fake_model, "Hola, ¿cómo estás?")

    assert decision == {
        "answer": "Pregúntame por un empleado (EMP-0001) o un departamento."
    }


def test_tokens_are_counted_by_words(fake_model):
    messages = [
        {"role": "user", "content": "Hola"},
        {"role": "assistant", "content": "Hola, dime"},
        {"role": "user", "content": "¿Quién es EMP-0001?"},
    ]

    reply = fake_model.complete(messages)

    assert reply.input_tokens == 6
    assert reply.output_tokens == len(reply.text.split())


def test_fake_models_answer_the_same_under_both_names():
    small = FakeModel(SMALL_MODEL, DEPARTMENTS).complete(QUESTION)
    large = FakeModel(LARGE_MODEL, DEPARTMENTS).complete(QUESTION)

    assert small.text == large.text
    assert (small.model, large.model) == (SMALL_MODEL, LARGE_MODEL)
    assert not small.cached


def test_gateway_sends_the_request_cloudflare_expects():
    sent = []

    def handler(request):
        sent.append(request)
        return gateway_response('{"answer": "Hola."}', 12, 3)

    reply = _gateway(handler, {"MODEL_MAX_TOKENS": "150"}).complete(QUESTION)

    request = sent[0]
    body = json.loads(request.content)
    assert str(request.url) == GATEWAY_URL
    assert request.headers["Authorization"] == "Bearer token-that-must-stay-secret"
    assert "cf-aig-cache-ttl" not in request.headers
    assert body["model"] == SMALL_MODEL
    assert body["max_tokens"] == 150
    assert body["temperature"] == 0
    assert body["messages"][-1] == QUESTION[0]
    assert (reply.text, reply.input_tokens, reply.output_tokens) == (
        '{"answer": "Hola."}',
        12,
        3,
    )


def test_gateway_cache_hit_marks_the_reply_as_cached():
    sent = []

    def handler(request):
        sent.append(request)
        headers = {"cf-aig-cache-status": "HIT"}
        return gateway_response('{"answer": "Hola."}', 12, 3, headers)

    model = _gateway(handler, {"CACHE_TTL_SECONDS": "300"})
    reply = model.complete(QUESTION)

    assert sent[0].headers["cf-aig-cache-ttl"] == "300"
    assert reply.cached


def test_gateway_puts_its_system_message_first():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return gateway_response('{"answer": "Hola."}', 12, 3)

    _gateway(handler).complete(QUESTION)

    messages = sent[0]["messages"]
    assert messages[0]["role"] == "system"
    assert messages[1:] == QUESTION


def test_fake_provider_builds_one_model_per_configured_name(directory):
    models = build_models(load_config({}), directory)

    assert set(models) == {SMALL_MODEL, LARGE_MODEL}
    assert all(isinstance(model, FakeModel) for model in models.values())
    assert models[LARGE_MODEL].complete(QUESTION).model == LARGE_MODEL


def test_gateway_provider_uses_the_injected_http_client(directory):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content)["model"])
        return gateway_response('{"answer": "Hola."}', 12, 3)

    config = load_config(GATEWAY_ENV)
    models = build_models(config, directory, gateway_http_client(handler))
    models[LARGE_MODEL].complete(QUESTION)

    assert sent == [LARGE_MODEL]


def _server_error(_request):
    """Gateway que responde con error del servidor."""
    return httpx.Response(500, json={"error": "boom"})


def _timeout(request):
    """Gateway que no responde a tiempo."""
    raise httpx.ReadTimeout("timeout", request=request)


def _missing_usage(_request):
    """Gateway que responde sin ``usage``."""
    return httpx.Response(200, json={"choices": []})


@pytest.mark.parametrize(
    "handler",
    [_server_error, _timeout, _missing_usage],
    ids=["server_error", "timeout", "incomplete_body"],
)
def test_gateway_failures_raise_model_unavailable(handler):
    with pytest.raises(ModelUnavailableError):
        _gateway(handler).complete(QUESTION)
