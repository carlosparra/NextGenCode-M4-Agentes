"""API tests for key checks that need a closer look than the scenarios."""

import io

from conftest import ANA_KEY, FakeClock

from app.observability import JsonLogger, client_var


def test_invalid_key_is_answered_before_the_body_is_validated(make_secure_client):
    client, _, _ = make_secure_client()
    response = client.post("/ask", json={"wrong": "body"})
    assert response.status_code == 401


def test_rate_limited_response_tells_how_long_to_wait(make_secure_client):
    client, _, _ = make_secure_client(env={"RATE_LIMIT_PER_MINUTE": "1"})
    headers = {"X-API-Key": ANA_KEY}
    client.get("/metrics", headers=headers)
    response = client.get("/metrics", headers=headers)
    assert response.status_code == 429
    assert response.headers["Retry-After"].isdigit()


def test_empty_key_list_leaves_ask_closed_in_development(make_secure_client):
    client, _, _ = make_secure_client(env={"API_KEYS": ""})
    response = client.post(
        "/ask", json={"question": "hi"}, headers={"X-API-Key": ""}
    )
    assert response.status_code == 401


def test_logger_adds_the_client_only_when_there_is_one():
    stream = io.StringIO()
    logger = JsonLogger("svc", FakeClock(), stream)
    logger.log("before")
    token = client_var.set("ana")
    try:
        logger.log("after")
    finally:
        client_var.reset(token)
    before, after = stream.getvalue().splitlines()
    assert '"client"' not in before
    assert '"client": "ana"' in after
