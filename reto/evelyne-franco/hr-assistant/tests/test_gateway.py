"""Pruebas unitarias del cliente de Cloudflare AI Gateway.

``GatewayModel(name=..., settings=..., client=...)`` recibe un
``httpx.Client`` inyectado. Aqui el cliente usa ``httpx.MockTransport``:
ninguna prueba toca la red ni gasta cuota.

:seealso: ``spec/03-costs.md`` punto 1 y ADR 0007.
"""

import json

import httpx
import pytest

from app.config import Settings
from app.gateway import GatewayModel
from app.llm import ModelUnavailable
from tests.conftest import MODEL_SMALL

TOKEN = "cf-token-do-not-leak"
EXPECTED_URL = (
    "https://gateway.ai.cloudflare.com/v1/acc-123/gw-456"
    "/workers-ai/v1/chat/completions"
)
QUESTION = [{"role": "user", "content": "Who is EMP-0001?"}]


def _ok_body(content='{"answer": "Hola"}'):
    """Cuerpo de una respuesta valida del gateway.

    :param content: Texto que devuelve el modelo.
    :type content: str
    :return: Cuerpo JSON con ``choices`` y ``usage``.
    :rtype: dict
    """
    return {
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 42, "completion_tokens": 7},
    }


def _model(handler, cache_ttl_seconds=0):
    """Crea un ``GatewayModel`` cuyo cliente responde con ``handler``.

    :param handler: Funcion que recibe la peticion y responde.
    :type handler: callable
    :param cache_ttl_seconds: TTL de la cache del gateway.
    :type cache_ttl_seconds: int
    :return: Modelo listo para llamar.
    :rtype: app.gateway.GatewayModel
    """
    settings = Settings(
        cf_account_id="acc-123",
        cf_gateway_id="gw-456",
        cf_api_token=TOKEN,
        model_max_tokens=300,
        model_temperature=0,
        cache_ttl_seconds=cache_ttl_seconds,
    )
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return GatewayModel(name=MODEL_SMALL, settings=settings, client=client)


def test_request_has_the_gateway_url_bearer_token_and_exact_body():
    """El POST va a la URL del gateway con ``Authorization: Bearer`` y
    el cuerpo ``{model, messages, max_tokens, temperature}``. El prompt
    de sistema va primero y la pregunta al final.
    """
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=_ok_body())

    _model(handler).complete(QUESTION)

    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert str(request.url) == EXPECTED_URL
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    body = json.loads(request.content)
    assert set(body) == {"model", "messages", "max_tokens", "temperature"}
    assert body["model"] == MODEL_SMALL
    assert body["max_tokens"] == 300
    assert body["temperature"] == 0
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][-1] == QUESTION[0]


def test_cache_header_is_sent_only_when_the_ttl_is_positive():
    """Con ``CACHE_TTL_SECONDS`` mayor que 0 se manda
    ``cf-aig-cache-ttl``; con 0, no.
    """
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=_ok_body())

    _model(handler, cache_ttl_seconds=0).complete(QUESTION)
    _model(handler, cache_ttl_seconds=60).complete(QUESTION)

    assert len(seen) == 2
    without_cache, with_cache = seen[0], seen[1]
    assert "cf-aig-cache-ttl" not in without_cache.headers
    assert with_cache.headers["cf-aig-cache-ttl"] == "60"


def test_usage_and_cache_hit_are_read_from_the_response():
    """Los tokens salen de ``usage`` y ``cf-aig-cache-status: HIT``
    marca la llamada como cacheada; sin ese encabezado no lo es.
    """

    def hit(_request):
        return httpx.Response(
            200, json=_ok_body(), headers={"cf-aig-cache-status": "HIT"}
        )

    def miss(_request):
        return httpx.Response(
            200, json=_ok_body(), headers={"cf-aig-cache-status": "MISS"}
        )

    cached = _model(hit, cache_ttl_seconds=60).complete(QUESTION)
    fresh = _model(miss, cache_ttl_seconds=60).complete(QUESTION)

    assert cached.text == '{"answer": "Hola"}'
    assert cached.input_tokens == 42
    assert cached.output_tokens == 7
    assert cached.cached is True
    assert fresh.cached is False


def test_every_gateway_failure_becomes_model_unavailable_without_the_token():
    """Timeout, status 4xx o 5xx, JSON roto, cuerpo sin ``choices`` o
    sin ``usage``: todo se convierte en ``ModelUnavailable`` y el
    mensaje nunca incluye el token.
    """

    def timeout(request):
        raise httpx.ReadTimeout("timed out", request=request)

    def unauthorized(_request):
        return httpx.Response(401, json={"error": "bad token"})

    def server_error(_request):
        return httpx.Response(500, text="upstream error")

    def broken_json(_request):
        return httpx.Response(200, text="{not json")

    def no_choices(_request):
        return httpx.Response(200, json={"usage": _ok_body()["usage"]})

    def no_usage(_request):
        return httpx.Response(200, json={"choices": _ok_body()["choices"]})

    failures = [timeout, unauthorized, server_error, broken_json, no_choices, no_usage]
    for handler in failures:
        with pytest.raises(ModelUnavailable) as info:
            _model(handler).complete(QUESTION)
        assert TOKEN not in str(info.value), handler.__name__
        assert TOKEN not in repr(info.value), handler.__name__
