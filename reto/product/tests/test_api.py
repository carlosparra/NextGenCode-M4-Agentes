"""Pruebas de las rutas de la API que no cubren los escenarios."""

import os

import pytest

from conftest import read_log


def test_health_reports_ok_and_the_process_id(client, settings):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "pid": os.getpid(),
        "version": settings.app_version,
    }


def test_home_page_has_the_form_and_never_uses_inner_html(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    for test_id in ("question", "send", "answer"):
        assert f'data-testid="{test_id}"' in response.text
    assert "innerHTML" not in response.text


def test_home_page_shows_the_request_id(client):
    assert "request_id" in client.get("/").text


def test_latency_is_measured_with_the_injected_clock(client, log_stream):
    response = client.post("/ask", json={"question": "   "})

    assert response.status_code == 422
    request_id = response.headers["X-Request-ID"]
    (event,) = [line for line in read_log(log_stream) if line["event"] == "request"]
    assert event["request_id"] == request_id
    assert (event["method"], event["path"], event["status"]) == ("POST", "/ask", 422)
    assert event["latency_ms"] == pytest.approx(250)


def test_metrics_endpoint_does_not_count_itself(client):
    client.get("/health")
    client.get("/metrics")

    assert client.get("/metrics").json()["requests"] == 1
