"""Pruebas del modelo real en AI Gateway, con ``httpx.MockTransport`` (sin red)."""

import json

import httpx
import pytest

from app.gateway import ModelUnavailableError

SMALL_MODEL = "@cf/meta/llama-3.1-8b-instruct-fast"
FAKE_TOKEN = "secret-token-xyz"
GATEWAY_URL = (
    "https://gateway.ai.cloudflare.com/v1/acct-123/hr-gateway"
    "/workers-ai/v1/chat/completions"
)
MESSAGES = [{"role": "user", "content": "¿Quién es EMP-0004?"}]


def test_gateway_request_has_url_token_and_body(
    make_gateway_models, gateway_environ, gateway_reply
):
    seen = []

    def handler(request):
        seen.append(request)
        return gateway_reply(
            '{"answer": "Hola"}', prompt_tokens=12, completion_tokens=4
        )

    _, _, models = make_gateway_models(gateway_environ, handler)
    reply = models[SMALL_MODEL].complete(MESSAGES)

    request = seen[0]
    assert request.method == "POST"
    assert str(request.url) == GATEWAY_URL
    assert request.headers["Authorization"] == f"Bearer {FAKE_TOKEN}"
    assert "cf-aig-cache-ttl" not in request.headers
    assert json.loads(request.content) == {
        "model": SMALL_MODEL,
        "messages": MESSAGES,
        "max_tokens": 300,
        "temperature": 0,
    }
    assert (reply.text, reply.input_tokens, reply.output_tokens) == (
        '{"answer": "Hola"}',
        12,
        4,
    )
    assert reply.cached is False


def test_cache_ttl_is_sent_and_a_cache_hit_is_reported(
    make_gateway_models, gateway_environ, gateway_reply
):
    seen = []

    def handler(request):
        seen.append(request)
        return gateway_reply('{"answer": "Hola"}', cache_status="HIT")

    gateway_environ["CACHE_TTL_SECONDS"] = "60"
    _, _, models = make_gateway_models(gateway_environ, handler)
    reply = models[SMALL_MODEL].complete(MESSAGES)

    assert seen[0].headers["cf-aig-cache-ttl"] == "60"
    assert reply.cached is True


@pytest.mark.parametrize("failure", ["server_error", "timeout", "no_choices"])
def test_gateway_failure_raises_model_unavailable(
    make_gateway_models, gateway_environ, failure
):
    def handler(request):
        if failure == "server_error":
            return httpx.Response(500, json={"error": "boom"})
        if failure == "timeout":
            raise httpx.ReadTimeout("too slow", request=request)
        return httpx.Response(200, json={"usage": {"prompt_tokens": 1}})

    _, _, models = make_gateway_models(gateway_environ, handler)

    with pytest.raises(ModelUnavailableError) as error:
        models[SMALL_MODEL].complete(MESSAGES)

    assert FAKE_TOKEN not in str(error.value)
