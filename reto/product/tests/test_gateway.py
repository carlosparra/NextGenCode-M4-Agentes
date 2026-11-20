"""Pruebas del modelo real a traves de Cloudflare AI Gateway (sin red)."""

import json

import httpx
import pytest

from conftest import CF_TOKEN, GATEWAY_ENV, SMALL_MODEL
from app.gateway import GatewayLLM, ModelUnavailable

GATEWAY_URL = (
    "https://gateway.ai.cloudflare.com/v1/acc-1/gw-1/workers-ai/v1/chat/completions"
)
MESSAGES = [{"role": "user", "content": "¿Quién es EMP-0004?"}]
OK_BODY = {
    "choices": [{"message": {"content": '{"answer": "Hola"}'}}],
    "usage": {"prompt_tokens": 120, "completion_tokens": 15},
}


def gateway(make_settings, handler, **env):
    """Crea el modelo de gateway con un transporte falso.

    :param make_settings: Fabrica de configuracion
    :type make_settings: callable
    :param handler: Funcion que recibe la peticion y devuelve la respuesta
    :type handler: callable
    :return: El modelo listo para ``complete``
    :rtype: GatewayLLM
    """
    settings = make_settings(**GATEWAY_ENV, **env)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return GatewayLLM(settings, SMALL_MODEL, client)


def test_gateway_sends_the_url_token_and_exact_body(make_settings):
    sent = []

    def handler(request):
        sent.append(request)
        return httpx.Response(200, json=OK_BODY)

    completion = gateway(make_settings, handler).complete(MESSAGES)

    request = sent[0]
    assert str(request.url) == GATEWAY_URL
    assert request.headers["Authorization"] == f"Bearer {CF_TOKEN}"
    assert json.loads(request.content) == {
        "model": SMALL_MODEL,
        "messages": MESSAGES,
        "max_tokens": 300,
        "temperature": 0,
    }
    assert "cf-aig-cache-ttl" not in request.headers
    assert (completion.text, completion.input_tokens, completion.output_tokens) == (
        '{"answer": "Hola"}',
        120,
        15,
    )
    assert (completion.model, completion.cached) == (SMALL_MODEL, False)


def test_gateway_sends_the_configured_output_cap_and_temperature(make_settings):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=OK_BODY)

    model = gateway(
        make_settings, handler, MODEL_MAX_TOKENS="50", MODEL_TEMPERATURE="0.7"
    )
    model.complete(MESSAGES)

    assert sent[0]["max_tokens"] == 50
    assert sent[0]["temperature"] == pytest.approx(0.7)


def test_cache_miss_is_not_counted_as_cached(make_settings):
    def handler(_request):
        return httpx.Response(
            200, json=OK_BODY, headers={"cf-aig-cache-status": "MISS"}
        )

    model = gateway(make_settings, handler, CACHE_TTL_SECONDS="3600")

    assert model.complete(MESSAGES).cached is False


@pytest.mark.parametrize("cache_status", ["HIT", "hit"])
def test_cache_ttl_is_sent_and_a_hit_is_reported(make_settings, cache_status):
    sent = []

    def handler(request):
        sent.append(request)
        return httpx.Response(
            200, json=OK_BODY, headers={"cf-aig-cache-status": cache_status}
        )

    model = gateway(make_settings, handler, CACHE_TTL_SECONDS="3600")

    assert model.complete(MESSAGES).cached is True
    assert sent[0].headers["cf-aig-cache-ttl"] == "3600"


def _status_500(_request):
    return httpx.Response(500, json={"error": "boom"})


def _status_401(_request):
    return httpx.Response(401, json={"error": "bad token"})


def _timeout(request):
    raise httpx.ReadTimeout("too slow", request=request)


def _no_usage(_request):
    return httpx.Response(200, json={"choices": OK_BODY["choices"]})


def _no_choices(_request):
    return httpx.Response(200, json={"usage": OK_BODY["usage"]})


@pytest.mark.parametrize(
    "handler", [_status_500, _status_401, _timeout, _no_usage, _no_choices]
)
def test_gateway_failure_is_model_unavailable_without_the_token(
    make_settings, handler
):
    model = gateway(make_settings, handler)

    with pytest.raises(ModelUnavailable) as error:
        model.complete(MESSAGES)

    assert CF_TOKEN not in str(error.value)
    assert CF_TOKEN not in repr(error.value)


# Token del "Authenticated Gateway" (CF_AIG_TOKEN), distinto de CF_API_TOKEN.
AIG_TOKEN = "aig-gateway-secret-value"
AIG_HEADER = "cf-aig-authorization"


def _sent_headers(make_settings, **env):
    """Hace una llamada exitosa y devuelve los encabezados enviados.

    :param make_settings: Fabrica de configuracion
    :type make_settings: callable
    :return: Encabezados de la unica peticion enviada
    :rtype: httpx.Headers
    """
    sent = []

    def handler(request):
        sent.append(request)
        return httpx.Response(200, json=OK_BODY)

    gateway(make_settings, handler, **env).complete(MESSAGES)
    return sent[0].headers


def test_gateway_token_is_sent_as_cf_aig_authorization(make_settings):
    headers = _sent_headers(make_settings, CF_AIG_TOKEN=AIG_TOKEN)

    assert headers[AIG_HEADER] == f"Bearer {AIG_TOKEN}"
    assert headers["Authorization"] == f"Bearer {CF_TOKEN}"


def test_without_gateway_token_the_cf_aig_authorization_header_is_not_sent(
    make_settings,
):
    headers = _sent_headers(make_settings)

    assert AIG_HEADER not in headers
    assert headers["Authorization"] == f"Bearer {CF_TOKEN}"


@pytest.mark.parametrize("handler", [_status_401, _timeout])
def test_gateway_failure_does_not_leak_the_gateway_token(make_settings, handler):
    model = gateway(make_settings, handler, CF_AIG_TOKEN=AIG_TOKEN)

    with pytest.raises(ModelUnavailable) as error:
        model.complete(MESSAGES)

    assert AIG_TOKEN not in str(error.value)
    assert AIG_TOKEN not in repr(error.value)
