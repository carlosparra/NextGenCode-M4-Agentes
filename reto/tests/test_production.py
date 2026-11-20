"""Pruebas de la prueba de humo, con un servidor simulado (sin red)."""

import httpx

from verification import production

NO_DATA = "No tengo ese dato en el directorio."


def fake_render(key_required=True, healthy=True, answer=NO_DATA):
    def handler(request):
        if request.url.path in ("/health", "/docs"):
            return httpx.Response(200 if healthy else 503)
        has_key = request.headers.get("X-API-Key") == "good-key"
        status = 200 if has_key or not key_required else 401
        return httpx.Response(status, json={"answer": answer})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_a_healthy_protected_service_passes(capsys):
    assert production.smoke("https://x", "good-key", fake_render())
    assert capsys.readouterr().out.count("[OK]") == 5


def test_a_service_without_keys_fails():
    open_service = fake_render(key_required=False)
    assert not production.smoke("https://x", "good-key", open_service)


def test_a_sleeping_service_fails():
    assert not production.smoke("https://x", "good-key", fake_render(healthy=False))


def test_a_service_that_invents_a_phone_fails(capsys):
    inventing = fake_render(answer="El teléfono de Ana López es 987654321.")
    assert not production.smoke("https://x", "good-key", inventing)
    assert "inventa o muestra un teléfono" in capsys.readouterr().out


def test_a_grouped_phone_also_fails():
    grouped = fake_render(answer="Su teléfono es (55) 1234-5678.")
    assert not production.smoke("https://x", "good-key", grouped)


def test_masked_phones_and_start_dates_pass():
    masked = fake_render(answer="Ana López ingresó el 2019-03-04. Tel: [TELEFONO].")
    assert production.smoke("https://x", "good-key", masked)


def test_the_key_must_come_from_the_environment(monkeypatch, capsys):
    monkeypatch.delenv("SMOKE_API_KEY", raising=False)
    assert production.main(["https://x"]) == 2
    assert "SMOKE_API_KEY" in capsys.readouterr().out
