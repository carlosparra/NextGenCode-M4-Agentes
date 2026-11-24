"""Modelo real (con transporte simulado), costos, logs, métricas y trazas."""

import io
import json

import httpx
import pytest

from app.clock import FixedClock
from app.config import load_settings
from app.llm.base import ModelUnavailable
from app.llm.costs import LlmSession, PriceTable, Route, choose_model
from app.llm.fake import FakeModel
from app.llm.gateway import GatewayModel
from app.domain.directory import Directory
from app.observability.logs import JsonLogger, request_id_var
from app.observability.metrics import Metrics, percentile
from app.observability.tracing import Tracer
from tests.conftest import NOW, ScriptedModel, run

GATEWAY_ENV = {
    "MODEL_PROVIDER": "gateway",
    "CF_ACCOUNT_ID": "acc",
    "CF_GATEWAY_ID": "gw",
    "CF_API_TOKEN": "tok",
    "CACHE_TTL_SECONDS": "60",
    "MODEL_RETRIES": "2",
}
OK_BODY = {
    "choices": [{"message": {"content": "hola"}}],
    "usage": {"prompt_tokens": 7, "completion_tokens": 2},
}


def gateway(handler, **env):
    settings = load_settings({**GATEWAY_ENV, **env})

    async def no_sleep(_):
        return None

    return GatewayModel(
        settings, transport=httpx.MockTransport(handler), sleep=no_sleep
    )


def test_gateway_sends_auth_cache_and_parses_usage():
    seen = {}

    def handler(request):
        seen.update(request.headers)
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=OK_BODY, headers={"cf-aig-cache-status": "HIT"})

    completion = run(
        gateway(handler).complete([{"role": "user", "content": "x"}], "m", 9)
    )
    assert completion.text == "hola" and completion.cached
    assert (completion.input_tokens, completion.output_tokens) == (7, 2)
    assert seen["url"].endswith("/v1/acc/gw/workers-ai/v1/chat/completions")
    assert (
        seen["cf-aig-authorization"] == "Bearer tok"
        and seen["cf-aig-cache-ttl"] == "60"
    )
    assert seen["body"]["max_tokens"] == 9 and seen["body"]["temperature"] == 0


def test_gateway_retries_then_gives_up():
    calls = []

    def flaky(request):
        calls.append(request)
        return (
            httpx.Response(503) if len(calls) < 3 else httpx.Response(200, json=OK_BODY)
        )

    assert run(gateway(flaky).complete([], "m", 5)).text == "hola"
    assert len(calls) == 3

    def bad_request(_):
        return httpx.Response(400)

    with pytest.raises(ModelUnavailable, match="http_400"):
        run(gateway(bad_request).complete([], "m", 5))

    def broken(_):
        raise httpx.ConnectError("down")

    with pytest.raises(ModelUnavailable, match="ConnectError"):
        run(gateway(broken, MODEL_RETRIES="0").complete([], "m", 5))

    def garbage(_):
        return httpx.Response(200, text="not json")

    with pytest.raises(ModelUnavailable, match="bad_response"):
        run(gateway(garbage).complete([], "m", 5))


def test_gateway_without_auth_header_when_disabled():
    seen = {}

    def handler(request):
        seen.update(request.headers)
        return httpx.Response(200, json=OK_BODY)

    model = gateway(handler, CF_GATEWAY_AUTH="false", CACHE_TTL_SECONDS="0")
    run(model.complete([], "m", 5))
    run(model.aclose())
    assert "cf-aig-authorization" not in seen and "cf-aig-cache-ttl" not in seen
    assert seen["cf-aig-skip-cache"] == "true"


def test_router_and_prices():
    assert (
        choose_model("¿Quién es EMP-1?", "s", "l", True, 80).reason == "simple_question"
    )
    assert choose_model("Compara áreas", "s", "l", True, 80).reason == "keyword:compara"
    assert choose_model("x" * 81, "s", "l", True, 80).reason == "long_question"
    assert choose_model("hola", "s", "l", False, 80).model == "l"
    prices = PriceTable({"m": {"input": 1.0, "output": 2.0}})
    assert prices.cost("m", 1_000_000, 500_000) == 2.0
    assert prices.cost("unknown", 10, 10) == 0.0


def test_session_counts_cached_calls_as_free():
    class Cached(ScriptedModel):
        """Modelo cuyas respuestas vienen de la caché del gateway."""

        async def complete(self, messages, model, max_tokens):
            completion = await super().complete(messages, model, max_tokens)
            return completion.__class__(completion.text, 10, 5, model, cached=True)

    session = LlmSession(
        Cached(["hola"]),
        PriceTable({"m": {"input": 1, "output": 1}}),
        Route("m", "r"),
        50,
        FixedClock(NOW),
    )
    assert run(session.chat([{"role": "user", "content": "x"}], agent="t")) == "hola"
    assert session.usage.cached_calls == 1 and session.usage.cost_usd == 0


def test_fake_model_respects_the_output_cap():
    directory = Directory.from_file(load_settings({}).employees_path)
    completion = run(
        FakeModel(directory).complete(
            [
                {"role": "system", "content": "[agent:hr]"},
                {"role": "user", "content": "¿qué tal?"},
            ],
            "m",
            3,
        )
    )
    assert completion.output_tokens == 3


def test_logger_masks_pii_and_writes_audit_file(tmp_path):
    stream = io.StringIO()
    audit = tmp_path / "audit.jsonl"
    logger = JsonLogger("svc", FixedClock(NOW), stream, audit_path=str(audit))
    token = request_id_var.set("rid-1")
    logger.audit("tool_call", args={"note": "llama al 2281234567"})
    logger.event("request", status=200)
    request_id_var.reset(token)
    lines = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert lines[0]["args"]["note"] == "llama al [PHONE]"
    assert (
        lines[0]["ts"] == "2026-11-24T12:00:00Z" and lines[0]["request_id"] == "rid-1"
    )
    assert len(audit.read_text(encoding="utf-8").splitlines()) == 1


def test_metrics_math():
    assert percentile([], 0.95) == 0.0
    assert percentile([1, 2, 3, 4], 0.5) == 2
    metrics = Metrics(slo_p95_ms=100)
    metrics.record_request(200, 50)
    metrics.record_request(500, 150)
    metrics.record_agent(
        {
            "input_tokens": 3,
            "cost_usd": 0.5,
            "tools": ["t"],
            "intent": "employee",
            "model": "m",
        }
    )
    snap = metrics.snapshot()
    assert snap["error_rate"] == 0.5 and not snap["slo"]["met"]
    assert snap["counters"]["tool_t"] == 1 and snap["cost_usd"] == 0.5
    assert 'name="status_500"' in metrics.prometheus("svc")


def test_tracer_is_off_without_key_and_hides_payloads():
    settings = load_settings({"LANGSMITH_TRACING": "true"})
    assert not Tracer(settings, env={}).enabled
    tracer = Tracer(settings, env={"LANGSMITH_API_KEY": "lsv2_fake"})
    assert tracer.enabled
    with tracer.scope("ask", {"request_id": "r"}):
        pass
    off = Tracer(load_settings({}), env={})
    with off.scope("ask", {}):
        pass
    off.flush()


def test_trace_payloads_are_hidden_or_masked():
    # pylint: disable=import-outside-toplevel,protected-access
    from app.observability.tracing import _hide

    assert _hide(True)({"q": "x@y.com"}) == {"hidden": True}
    assert _hide(False)({"q": "x@y.com"}) == {"q": "[EMAIL]"}
