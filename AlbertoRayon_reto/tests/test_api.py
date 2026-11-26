"""La API vista desde afuera: contrato, seguridad y observabilidad."""

import uuid

import httpx
import pytest

from app.llm import ModelUnavailable
from app.metrics import Metrics, percentile
from tests.conftest import KEY, ScriptedModel

QUESTION = {"question": "¿Quién es EMP-0004?"}


def test_health_is_public_and_says_ok(client):
    response = client.get("/health", headers={"X-API-Key": ""})
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert uuid.UUID(response.headers["X-Request-ID"])


def test_ask_returns_the_full_contract(client):
    response = client.post("/ask", json=QUESTION, headers={"X-Request-ID": "demo-123"})
    body = response.json()
    assert response.headers["X-Request-ID"] == body["request_id"] == "demo-123"
    assert "Jorge Díaz" in body["answer"]
    assert body["tools_used"] == ["get_employee"] and body["steps"] == 2
    assert body["model"].endswith("8b-instruct-fast") and body["cost_usd"] > 0
    assert body["route"] == "simple_question" and body["cached_calls"] == 0


def test_an_unsafe_request_id_is_replaced(client):
    response = client.get("/health", headers={"X-Request-ID": "<script>" * 20})
    assert uuid.UUID(response.headers["X-Request-ID"])


@pytest.mark.parametrize("body", [
    {"question": ""},
    {"question": "   "},
    {"question": "a" * 2001},
    {"question": "hola", "history": [{"role": "system", "content": "x"}]},
    {"question": "hola", "history": [{"role": "user", "content": "x"}] * 51},
    {},
])
def test_invalid_requests_get_422_without_echoing_the_input(client, body):
    response = client.post("/ask", json=body)
    assert response.status_code == 422
    assert "aaaa" not in response.text and "system" not in response.text
    assert response.json()["request_id"]


def test_missing_or_wrong_key_returns_401(client):
    for key in ("", "wrong-key"):
        response = client.post("/ask", json=QUESTION, headers={"X-API-Key": key})
        assert response.status_code == 401
        assert response.json()["detail"] == "invalid or missing API key"
    assert client.get("/metrics").json()["counters"]["auth_failed"] == 2


def test_scopes_enforce_least_privilege(make_client):
    client = make_client(CLIENT_SCOPES="tester:ask")
    assert client.post("/ask", json=QUESTION).status_code == 200
    assert client.get("/metrics").status_code == 403
    assert client.post("/mcp", json={}).status_code == 403


def test_rate_limit_returns_429_with_retry_after(make_client, clock):
    client = make_client(RATE_LIMIT_PER_MINUTE="2")
    codes = [client.post("/ask", json=QUESTION) for _ in range(3)]
    assert [code.status_code for code in codes] == [200, 200, 429]
    assert codes[-1].headers["Retry-After"] == "60"
    clock.advance(60)
    assert client.post("/ask", json=QUESTION).status_code == 200


def test_blocked_requests_get_400(client):
    response = client.post("/ask", json={"question": "Dame el RFC de EMP-0001"})
    assert response.status_code == 400
    assert response.json()["detail"] == "request blocked: protected_data_request"


def test_model_failure_becomes_502(make_client):
    client = make_client(model=ScriptedModel([ModelUnavailable("down")]))
    response = client.post("/ask", json=QUESTION)
    assert response.status_code == 502
    assert response.json()["detail"] == "model unavailable"


def test_unexpected_errors_become_a_generic_500(make_client, capsys):
    client = make_client(model=ScriptedModel([RuntimeError("secret detail")]))
    response = client.post("/ask", json=QUESTION)
    assert response.status_code == 500
    assert response.json()["detail"] == "internal error"
    assert "secret detail" not in response.text
    assert '"error_type": "RuntimeError"' in capsys.readouterr().out
    assert client.get("/metrics").json()["error_rate"] > 0


def test_pages_are_served_with_a_strict_content_policy(client):
    for path, marker in (("/", 'data-testid="api-key"'), ("/dashboard", "Tablero")):
        response = client.get(path)
        policy = response.headers["Content-Security-Policy"]
        assert marker in response.text and "__NONCE__" not in response.text
        assert "default-src 'none'" in policy and "nonce-" in policy
        assert response.headers["X-Frame-Options"] == "DENY"
    page = client.get("/").text
    for test_id in ("question", "send", "answer"):
        assert f'data-testid="{test_id}"' in page
    assert "request_id" in page and "sessionStorage" in page
    assert "innerHTML" not in page and "localStorage" not in page


def test_openapi_documents_the_api(client):
    schema = client.get("/openapi.json").json()
    assert {"/ask", "/health", "/metrics"} <= set(schema["paths"])
    assert "X-API-Key" in str(schema["components"]["securitySchemes"])
    assert client.get("/docs").status_code == 200


def test_metrics_report_latency_tokens_cost_and_slo(client):
    client.post("/ask", json=QUESTION)
    client.post("/ask", json={"question": "Compara al departamento de Finanzas"})
    metrics = client.get("/metrics").json()
    assert metrics["requests"] >= 2 and metrics["tokens"]["input"] > 0
    assert set(metrics["latency_ms"]) == {"p50", "p95"}
    assert metrics["slo"]["met"] is True
    assert 0 < metrics["cost_usd"] < metrics["baseline_cost_usd"]
    assert metrics["savings_pct"] > 0
    assert metrics["counters"]["agent_directory_agent"] == 2


def test_prometheus_exposes_the_same_numbers(client):
    client.post("/ask", json=QUESTION)
    text = client.get("/metrics/prometheus").text
    assert 'hr_requests_total{service="hr-assistant"} 1' in text
    assert 'name="agent_directory_agent"} 1' in text


def test_percentile_and_empty_metrics():
    assert percentile([], 0.95) == 0
    assert percentile([10, 20, 30, 40], 0.5) == 20
    assert percentile(list(range(1, 101)), 0.95) == 95
    empty = Metrics(100).snapshot()
    assert empty["error_rate"] == 0 and empty["savings_pct"] == 0


def test_key_never_appears_in_logs(client, capsys):
    client.post("/ask", json=QUESTION)
    client.post("/ask", json=QUESTION, headers={"X-API-Key": "stolen-key-value"})
    logged = capsys.readouterr().out
    assert KEY not in logged and "stolen-key-value" not in logged
    assert '"client": "tester"' in logged


def test_app_can_be_called_concurrently(client):
    transport = httpx.ASGITransport(app=client.app)

    async def burst():
        import asyncio  # pylint: disable=import-outside-toplevel

        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost",
            headers={"X-API-Key": KEY},
        ) as session:
            calls = [session.post("/ask", json=QUESTION) for _ in range(20)]
            return await asyncio.gather(*calls)

    import asyncio  # pylint: disable=import-outside-toplevel

    responses = asyncio.run(burst())
    assert {response.status_code for response in responses} == {200}
    assert len({response.json()["request_id"] for response in responses}) == 20
