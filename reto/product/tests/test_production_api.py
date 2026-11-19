"""Pruebas de la clave en la API, la pagina web y la prueba de humo."""

import importlib.util
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from conftest import API_KEY_HEADER, TEST_API_KEY

PRODUCT_DIR = Path(__file__).resolve().parent.parent
SMOKE_SCRIPT = PRODUCT_DIR / "scripts" / "smoke.py"
URL = "https://hr-assistant.example.com"


def load_smoke():
    """Importa ``scripts/smoke.py`` como modulo.

    :return: El modulo de la prueba de humo
    :rtype: module
    """
    spec = importlib.util.spec_from_file_location("smoke", SMOKE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_service(calls):
    """Servicio falso que se comporta como el producto publicado.

    :param calls: Lista donde se anota cada peticion recibida
    :type calls: list
    :return: Transporte de ``httpx`` sin red
    :rtype: httpx.MockTransport
    """

    def handler(request):
        calls.append(request)
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.headers.get(API_KEY_HEADER) == TEST_API_KEY:
            return httpx.Response(200, json={"answer": "Jorge Díaz"})
        return httpx.Response(401, json={"detail": "invalid or missing API key"})

    return httpx.MockTransport(handler)


def test_missing_key_is_reported_before_invalid_fields(client):
    unauthenticated = TestClient(client.app)

    response = unauthenticated.post("/ask", json={"question": ""})

    assert response.status_code == 401
    assert response.headers["X-Request-ID"]


def test_page_has_a_password_key_field_kept_only_in_session_storage(client):
    page = client.get("/").text

    assert 'data-testid="api-key"' in page
    assert 'type="password"' in page
    assert "sessionStorage" in page
    assert "X-API-Key" in page
    assert "localStorage" not in page
    assert TEST_API_KEY not in page


def test_smoke_exits_zero_only_when_all_three_checks_pass(monkeypatch, capsys):
    smoke = load_smoke()

    monkeypatch.setenv("SMOKE_API_KEY", TEST_API_KEY)
    assert smoke.main([URL], transport=fake_service([])) == 0
    output = capsys.readouterr().out
    assert (output.count("[OK]"), output.count("[FAIL]")) == (3, 0)
    assert TEST_API_KEY not in output

    monkeypatch.setenv("SMOKE_API_KEY", "wrong-key-value-123456")
    assert smoke.main([URL], transport=fake_service([])) != 0
    output = capsys.readouterr().out
    assert (output.count("[OK]"), output.count("[FAIL]")) == (2, 1)


def test_smoke_without_a_key_fails_before_calling_the_network(monkeypatch):
    monkeypatch.delenv("SMOKE_API_KEY", raising=False)
    calls = []

    code = load_smoke().main([URL], transport=fake_service(calls))

    assert code != 0
    assert not calls
