"""Unit tests for GatewayModel, using httpx.MockTransport (no network)."""

import httpx
import pytest

from conftest import GATEWAY_ENV, gateway_reply

from app.config import load_settings
from app.llm import Completion, GatewayModel, ModelUnavailable

MESSAGES = [{"role": "user", "content": "hello"}]


def _model(handler, **extra):
    """Build a GatewayModel whose HTTP client answers with ``handler``."""
    env = {**GATEWAY_ENV, "MODEL_MAX_TOKENS": "123", **extra}
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return GatewayModel("small-model", load_settings(env), client=client)


def test_gateway_request_has_url_auth_and_body():
    seen = []

    def handler(request):
        seen.append(request)
        return gateway_reply()

    _model(handler).generate(MESSAGES)
    request = seen[0]
    assert str(request.url) == (
        "https://gateway.ai.cloudflare.com/v1/acct/gw/"
        "workers-ai/v1/chat/completions"
    )
    assert request.headers["Authorization"] == "Bearer tok"
    body = httpx.Response(200, content=request.content).json()
    assert body == {"model": "small-model", "messages": MESSAGES,
                    "max_tokens": 123, "temperature": 0}


def test_cache_ttl_header_is_sent_only_when_positive():
    seen = []

    def handler(request):
        seen.append(request)
        return gateway_reply()

    _model(handler, CACHE_TTL_SECONDS="60").generate(MESSAGES)
    _model(handler, CACHE_TTL_SECONDS="0").generate(MESSAGES)
    assert seen[0].headers["cf-aig-cache-ttl"] == "60"
    assert "cf-aig-cache-ttl" not in seen[1].headers


def test_completion_reads_usage_and_cache_status():
    hit = _model(lambda r: gateway_reply("hi", 11, 7, "HIT")).generate(MESSAGES)
    miss = _model(lambda r: gateway_reply("hi", 11, 7, "MISS")).generate(MESSAGES)
    assert hit == Completion(text="hi", input_tokens=11, output_tokens=7,
                             cached=True)
    assert miss.cached is False
    assert _model(lambda r: gateway_reply("hi")).complete(MESSAGES) == "hi"


def test_every_gateway_failure_becomes_model_unavailable():
    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)

    handlers = [
        lambda r: httpx.Response(500, text="boom"),
        lambda r: httpx.Response(200, text="not json"),
        lambda r: httpx.Response(200, json={"choices": []}),
        timeout,
    ]
    for handler in handlers:
        with pytest.raises(ModelUnavailable):
            _model(handler).generate(MESSAGES)
