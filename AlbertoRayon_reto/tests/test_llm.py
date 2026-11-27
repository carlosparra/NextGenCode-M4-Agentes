"""Modelos, precios y enrutamiento."""

import json

import httpx
import pytest

from app.llm import (FakeModel, GatewayModel, ModelCaller, ModelUnavailable, Prices,
                     Usage, choose_model)
from tests.conftest import ScriptedModel, make_settings

SMALL = "@cf/meta/llama-3.1-8b-instruct-fast"
LARGE = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
GATEWAY = {"MODEL_PROVIDER": "gateway", "CF_ACCOUNT_ID": "acc", "CF_API_TOKEN": "tok"}


def user(text):
    return [{"role": "user", "content": text}]


@pytest.mark.parametrize("question, env, model, reason", [
    ("¿Quién es EMP-0004?", {}, SMALL, "simple_question"),
    ("Compara a Ana con Jorge", {}, LARGE, "keyword:compara"),
    ("¿Por qué hay una baja?", {}, LARGE, "keyword:por que"),
    ("x" * 81, {}, LARGE, "long_question"),
    ("¿Quién es EMP-0004?", {"ROUTING": "false"}, LARGE, "routing_off"),
])
def test_router_picks_the_model_with_a_rule(question, env, model, reason):
    assert choose_model(question, make_settings(**env)) == (model, reason)


def test_prices_are_per_million_tokens():
    prices = Prices.from_file(make_settings().prices_path)
    assert prices.cost(SMALL, 1_000_000, 0) == pytest.approx(0.045)
    assert prices.cost(LARGE, 0, 1_000_000) == pytest.approx(2.253)
    assert prices.cost("unknown", 100, 100) == 0


def test_fake_model_follows_its_rules_in_order():
    fake = FakeModel(["Finanzas", "Tecnología"])
    assert json.loads(fake.complete(user("¿Quién es EMP-0002?"), SMALL).content) == {
        "thought": "Necesito la herramienta get_employee.", "tool": "get_employee",
        "args": {"employee_id": "EMP-0002"},
    }
    vacations = fake.complete(user("Vacaciones de EMP-0002"), SMALL).content
    assert json.loads(vacations)["tool"] == "get_vacation_balance"
    department = fake.complete(user("gente de tecnologia"), SMALL).content
    assert json.loads(department)["args"] == {"department": "Tecnología"}
    result = fake.complete(user("Resultado de la herramienta: dato"), SMALL)
    assert json.loads(result.content) == {"answer": "Según el directorio: dato"}
    assert "Pregúntame" in fake.complete(user("hola"), SMALL).content


def test_fake_model_counts_tokens_by_words():
    completion = FakeModel([]).complete(user("uno dos tres"), SMALL)
    assert completion.input_tokens == 3
    assert completion.output_tokens == len(completion.content.split())


def gateway(handler, **env):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return GatewayModel(make_settings(**GATEWAY, **env), client)


def test_gateway_sends_the_request_the_spec_describes():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "hola"}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 3},
        }, headers={"cf-aig-cache-status": "HIT"})

    model = gateway(handler, CACHE_TTL_SECONDS="60", CF_AIG_TOKEN="gw")
    completion = model.complete(user("hola"), SMALL)
    assert seen["url"].endswith("/v1/acc/default/workers-ai/v1/chat/completions")
    assert seen["headers"]["authorization"] == "Bearer tok"
    assert seen["headers"]["cf-aig-authorization"] == "Bearer gw"
    assert seen["headers"]["cf-aig-cache-ttl"] == "60"
    assert seen["body"]["max_tokens"] == 300
    assert (completion.input_tokens, completion.output_tokens) == (12, 3)
    assert completion.cached


def test_gateway_skips_the_cache_when_ttl_is_zero():
    seen = {}

    def handler(request):
        seen["headers"] = request.headers
        return httpx.Response(200, json={"choices": [{"message": {"content": "x"}}]})

    gateway(handler).complete(user("hola"), SMALL)
    assert seen["headers"]["cf-aig-skip-cache"] == "true"
    assert "cf-aig-cache-ttl" not in seen["headers"]


def test_workers_provider_calls_workers_ai_directly_without_cache_headers():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        return httpx.Response(200, json={"choices": [{"message": {"content": "x"}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    settings = make_settings(**{**GATEWAY, "MODEL_PROVIDER": "workers"})
    GatewayModel(settings, client).complete(user("hola"), SMALL)
    assert seen["url"].endswith("/accounts/acc/ai/v1/chat/completions")
    assert "cf-aig-skip-cache" not in seen["headers"]


@pytest.mark.parametrize("response", [
    httpx.Response(401, json={"errors": [{"code": 2009}]}),
    httpx.Response(200, json={"unexpected": True}),
    httpx.Response(200, text="not json"),
])
def test_gateway_failures_become_model_unavailable_without_the_token(response):
    with pytest.raises(ModelUnavailable) as error:
        gateway(lambda request: response).complete(user("hola"), SMALL)
    assert "tok" not in str(error.value)


def test_cached_calls_cost_nothing():
    prices = Prices.from_file(make_settings().prices_path)
    usage = Usage()
    caller = ModelCaller(ScriptedModel(["uno", "dos"]), prices)
    assert caller.call(user("hola"), LARGE, usage) == "uno"
    assert usage.cost_usd > 0 and usage.steps == 1

    class Cached(ScriptedModel):
        """Modelo cuya respuesta viene de la caché del gateway."""

        def complete(self, messages, model):
            completion = super().complete(messages, model)
            return type(completion)(completion.content, 10, 5, model, cached=True)

    cached_usage = Usage()
    ModelCaller(Cached(["uno"]), prices).call(user("hola"), LARGE, cached_usage)
    assert cached_usage.cost_usd == 0 and cached_usage.cached_calls == 1
