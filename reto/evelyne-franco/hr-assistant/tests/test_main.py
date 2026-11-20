"""Pruebas unitarias de los endpoints de la aplicacion FastAPI.

Verifica las rutas GET /health y GET /, mas el formato completo
de la respuesta de POST /ask.  Los casos de validacion (422,
history, fallback) ya los cubren los escenarios Gherkin.
"""

import re

from tests.conftest import TEST_KEY


def test_health_returns_ok_with_pid(client):
    """GET /health devuelve status 'ok' y un pid entero."""
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert isinstance(body["pid"], int)


def test_home_page_serves_html(client):
    """GET / devuelve HTML con los data-testid requeridos."""
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_ask_response_has_all_required_fields(client):
    """POST /ask devuelve answer, steps, tools_used, input_tokens,
    output_tokens y, desde la sesion 3, model, route, cached_calls
    y cost_usd.
    """
    response = client.post(
        "/ask",
        json={"question": "Who is EMP-0001?"},
    )
    assert response.status_code == 200
    body = response.json()
    for field in (
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
    ):
        assert field in body, f"Missing field: {field}"


# -- Sesion 4: clave por cliente ---------------------------------------


def test_home_page_has_a_password_key_field_kept_in_session_storage(harness):
    """La pagina tiene el campo ``api-key`` tipo contrasena, guarda la
    clave en ``sessionStorage`` (nunca en ``localStorage``), la manda en
    ``X-API-Key`` y trae los mensajes de 401 y 429 en espanol.
    """
    html = harness.anonymous.get("/").text

    field = re.search(r"<input[^>]*data-testid=\"api-key\"[^>]*>", html)
    assert field is not None
    assert 'type="password"' in field.group(0)
    assert "sessionStorage" in html
    assert "localStorage" not in html
    assert "X-API-Key" in html
    assert "Clave inválida" in html
    assert "Demasiadas preguntas" in html
    assert TEST_KEY not in html


def test_rejected_request_is_logged_without_client_or_key(harness):
    """Un 401 deja su evento ``request`` (sin ``client``) y la clave
    equivocada no aparece en el log.
    """
    wrong_key = "wrong-key-0123456789abc"

    response = harness.anonymous.post(
        "/ask",
        json={"question": "Who is EMP-0001?"},
        headers={"X-API-Key": wrong_key},
    )

    assert response.status_code == 401
    (event,) = harness.events("request")
    assert event["status"] == 401
    assert "client" not in event
    assert wrong_key not in harness.log_text()
