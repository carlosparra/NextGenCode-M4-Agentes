"""Pruebas unitarias de la API (``app.main.create_app``)."""

import json

import httpx

from conftest import TEST_API_KEY, TEST_CLIENT, FakeClock, ScriptedModel


def test_ask_returns_every_response_field(build_client):
    client = build_client()

    response = client.post("/ask", json={"question": "¿Quién es EMP-0001?"})

    body = response.json()
    assert response.status_code == 200
    assert set(body) == {
        "answer",
        "steps",
        "tools_used",
        "input_tokens",
        "output_tokens",
        "request_id",
        "model",
        "route",
        "cached_calls",
        "cost_usd",
    }
    assert body["input_tokens"] > 0
    assert body["output_tokens"] > 0


def test_question_limit_comes_from_configuration(build_client):
    client = build_client({"MAX_QUESTION_CHARS": "10"})

    accepted = client.post("/ask", json={"question": "a" * 10})
    rejected = client.post("/ask", json={"question": "a" * 11})

    assert accepted.status_code == 200
    assert rejected.status_code == 422


def test_api_does_not_remember_previous_requests(build_client):
    answer = (json.dumps({"answer": "Listo."}), 1, 1)
    model = ScriptedModel([answer, answer])
    client = build_client(None, model)
    history = [{"role": "user", "content": "Recuerda esto"}]

    client.post("/ask", json={"question": "Primera", "history": history})
    client.post("/ask", json={"question": "Segunda"})

    second_contents = [message["content"] for message in model.calls[1]]
    assert "Recuerda esto" not in second_contents
    assert "Primera" not in second_contents


def test_metrics_cost_starts_at_zero(build_client):
    response = build_client().get("/metrics")

    assert response.status_code == 200
    assert response.json()["cost_usd"] == 0


def test_model_unavailable_error_keeps_the_request_id(build_gateway_client):
    def handler(_request):
        return httpx.Response(500, json={"error": "boom"})

    client = build_gateway_client(handler)
    response = client.post(
        "/ask",
        json={"question": "Hola"},
        headers={"X-Request-ID": "req-costs-1"},
    )

    assert response.status_code == 502
    assert response.json() == {
        "detail": "model unavailable",
        "request_id": "req-costs-1",
    }
    assert response.headers["X-Request-ID"] == "req-costs-1"


def test_routing_lowers_the_cost_of_the_same_question(build_client):
    question = {"question": "¿Quién es EMP-0004?"}

    with_routing = build_client().post("/ask", json=question).json()
    baseline = build_client({"ROUTING": "false"}).post("/ask", json=question).json()

    assert with_routing["answer"] == baseline["answer"]
    assert 0 < with_routing["cost_usd"] < baseline["cost_usd"]


def test_missing_key_is_rejected_before_the_body_is_validated(build_client):
    client = build_client(api_key=None)

    response = client.post("/ask", json={"question": ""})

    assert response.status_code == 401


def test_rejections_have_an_exact_body_and_keep_the_request_id(build_client):
    keyless = build_client(api_key=None)
    limited = build_client({"RATE_LIMIT_PER_MINUTE": "1"}, clock=FakeClock())

    unauthorized = keyless.get("/metrics", headers={"X-Request-ID": "req-401"})
    limited.post("/ask", json={"question": "Hola"})
    throttled = limited.post(
        "/ask", json={"question": "Hola"}, headers={"X-Request-ID": "req-429"}
    )

    assert unauthorized.status_code == 401
    assert unauthorized.json() == {"detail": "invalid or missing API key"}
    assert unauthorized.headers["X-Request-ID"] == "req-401"
    assert throttled.status_code == 429
    assert throttled.json() == {"detail": "rate limit exceeded"}
    assert throttled.headers["X-Request-ID"] == "req-429"
    assert throttled.headers["Retry-After"] == "60"


def test_client_is_logged_in_request_audit_and_agent_run(build_client, capsys):
    client = build_client()

    response = client.post("/ask", json={"question": "¿Quién es EMP-0004?"})

    output = capsys.readouterr().out
    events = [json.loads(line) for line in output.splitlines() if line.startswith("{")]
    by_event = {event["event"]: event for event in events}
    assert response.status_code == 200
    assert {"request", "audit", "agent_run"} <= set(by_event)
    for name in ("request", "audit", "agent_run"):
        assert by_event[name]["client"] == TEST_CLIENT
    assert TEST_API_KEY not in output


def test_pii_is_masked_before_the_model_and_in_the_answer(build_client):
    reply = (json.dumps({"answer": "Su RFC es LOPA800101AB1"}), 1, 1)
    model = ScriptedModel([reply])
    client = build_client(None, model)
    history = [{"role": "user", "content": "Mi tel es 55 1234 5678"}]

    response = client.post(
        "/ask", json={"question": "Escribe a ana@empresa.com", "history": history}
    )

    sent = json.dumps(model.calls[0], ensure_ascii=False)
    assert "ana@empresa.com" not in sent
    assert "55 1234 5678" not in sent
    assert "[email oculto]" in sent
    assert response.json()["answer"] == "Su RFC es [rfc oculto]"
