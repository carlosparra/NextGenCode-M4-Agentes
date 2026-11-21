"""Pruebas del gateway simulado de la verificación, sin correr el producto."""

import json

import httpx

from verification import gateway_harness as harness

SYSTEM = {"role": "system", "content": "instrucciones"}


def user(text):
    return {"role": "user", "content": text}


def reply_to(question, seen=None, extra=()):
    messages = [SYSTEM, user(question), *extra]
    return harness.respond(messages, {} if seen is None else seen)


def test_a_plain_question_gets_a_tool_request_then_an_answer():
    first = json.loads(reply_to("¿Quién es EMP-0001?"))
    assert first == {"tool": "get_employee", "args": {"employee_id": "EMP-0001"}}
    result = user(harness.TOOL_PREFIX + "EMP-0001 Ana López")
    last = json.loads(reply_to("¿Quién es EMP-0001?", extra=[result]))
    assert "Ana López" in last["answer"]


def test_the_messy_scenario_mixes_a_tool_request_with_an_invented_answer():
    text = reply_to("¿Quién es EMP-0004?")
    assert text.startswith(harness.TOOL_PREFIX)
    assert '"tool": "get_employee"' in text and '"answer"' in text


def test_the_recovery_scenario_fails_once_and_then_answers():
    seen = {}
    assert "{" not in reply_to("EMP-0002", seen)
    assert json.loads(reply_to("EMP-0002", seen)) == {"answer": "Recuperado"}


def test_the_never_valid_scenario_never_returns_json():
    seen = {}
    assert [reply_to("EMP-0003", seen) for _ in range(3)] == ["not json"] * 3


def test_a_question_without_an_employee_gets_a_plain_answer():
    assert "answer" in json.loads(reply_to("hola"))
    assert "answer" in json.loads(harness.respond([SYSTEM], {}))


def post(handler, url=harness.URL, token=harness.TOKEN):
    body = {"model": "m", "messages": [SYSTEM, user("EMP-0001")]}
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        return client.post(url, json=body, headers={"Authorization": f"Bearer {token}"})


def test_the_handler_answers_like_cloudflare_and_logs_the_request(tmp_path):
    log = tmp_path / "requests.jsonl"
    response = post(harness.build_handler(log))
    data = response.json()
    assert response.status_code == 200
    assert data["usage"]["prompt_tokens"] > 0
    assert json.loads(data["choices"][0]["message"]["content"])["tool"]
    assert json.loads(log.read_text(encoding="utf-8"))["messages"][0] == SYSTEM


def test_the_handler_rejects_a_wrong_url_or_token(tmp_path):
    handler = harness.build_handler(tmp_path / "requests.jsonl")
    assert post(handler, url=harness.URL + "/x").status_code == 404
    assert post(handler, token="other").status_code == 401
    assert not (tmp_path / "requests.jsonl").exists()


def test_install_answers_gateway_calls_and_can_be_undone(tmp_path, monkeypatch):
    restore = harness.install(harness.build_handler(tmp_path / "requests.jsonl"))
    try:
        with httpx.Client() as client:
            body = {"model": "m", "messages": [SYSTEM, user("EMP-0001")]}
            headers = {"Authorization": f"Bearer {harness.TOKEN}"}
            response = client.post(harness.URL, json=body, headers=headers)
            assert response.status_code == 200
    finally:
        restore()
    calls = []
    monkeypatch.setattr(
        httpx.HTTPTransport,
        "handle_request",
        lambda self, request: calls.append(request) or httpx.Response(204),
    )
    with httpx.Client() as client:
        assert client.get("https://example.com/").status_code == 204
    assert len(calls) == 1


def test_other_hosts_still_go_through_the_real_transport(monkeypatch):
    seen = []
    monkeypatch.setattr(
        httpx.HTTPTransport,
        "handle_request",
        lambda self, request: seen.append(str(request.url)) or httpx.Response(204),
    )
    transport = harness.GatewayOnlyTransport(lambda request: httpx.Response(500))
    request = httpx.Request("GET", "https://example.com/")
    assert transport.handle_request(request).status_code == 204
    assert seen == ["https://example.com/"]
