"""Pruebas de la prueba de humo, con un servidor simulado (sin red)."""

import json

import httpx

from verification import production

GOOD_ANSWER = "Según el directorio: Jorge Díaz, Ventas"
GOOD_SCHEMA = {"paths": {"/health": {}, "/ask": {}, "/metrics": {}}}
FAILURE_ANSWER = (
    "No pude completar la respuesta. Intenta con una pregunta más concreta."
)


def fake_render(**options):
    """Arma un cliente que simula el servicio publicado.

    Opciones, todas opcionales: ``key_required`` (si ``/ask`` exige la clave,
    verdadero por omisión), ``healthy`` (si ``/health`` responde 200, verdadero
    por omisión), ``answer`` (texto del campo ``answer``), ``body`` (cuerpo en
    crudo que reemplaza al JSON de ``/ask``), ``echo`` (si la respuesta repite
    la pregunta, como un servicio que no enmascara), ``pii_status`` (código
    que devuelve ``/ask`` a la pregunta con datos personales) y ``schema``
    (cuerpo de ``/openapi.json``; ``None`` simula que no existe).

    :param options: Opciones del servicio simulado
    :type options: object
    :return: Cliente con transporte simulado
    :rtype: httpx.Client
    """
    answer = options.get("answer", GOOD_ANSWER)
    pii_status = options.get("pii_status", 200)
    schema = options.get("schema", GOOD_SCHEMA)

    def handler(request):
        if request.url.path == "/health":
            return httpx.Response(200 if options.get("healthy", True) else 503)
        if request.url.path == "/openapi.json":
            return (httpx.Response(404) if schema is None
                    else httpx.Response(200, json=schema))
        has_key = request.headers.get("X-API-Key") == "good-key"
        if not has_key and options.get("key_required", True):
            return httpx.Response(401)
        question = json.loads(request.content)["question"]
        if production.PII_MARKER in question and pii_status != 200:
            return httpx.Response(pii_status)
        if options.get("body") is not None:
            return httpx.Response(200, content=options["body"])
        reply = question if options.get("echo") else answer
        return httpx.Response(200, json={"answer": reply})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_a_healthy_protected_service_passes(capsys):
    assert production.smoke("https://x", "good-key", fake_render())
    assert capsys.readouterr().out.count("[OK]") == 6


def test_a_service_without_keys_fails():
    open_service = fake_render(key_required=False)
    assert not production.smoke("https://x", "good-key", open_service)


def test_a_sleeping_service_fails():
    assert not production.smoke("https://x", "good-key", fake_render(healthy=False))


def test_the_fixed_failure_message_fails_even_with_status_200(capsys):
    client = fake_render(answer=FAILURE_ANSWER)
    assert not production.smoke("https://x", "good-key", client)
    out = capsys.readouterr().out
    assert "[FAIL] POST /ask con clave -> la respuesta trae al empleado" in out
    assert FAILURE_ANSWER not in out


def test_an_answer_without_the_employee_fails():
    client = fake_render(answer="Pregúntame por un empleado (EMP-0001).")
    assert not production.smoke("https://x", "good-key", client)


def test_a_body_that_is_not_json_fails_without_raising():
    client = fake_render(body=b"<html>gateway</html>")
    assert not production.smoke("https://x", "good-key", client)


def test_a_body_without_answer_fails_without_raising():
    client = fake_render(body=b'{"detail": "x"}')
    assert not production.smoke("https://x", "good-key", client)


def test_the_answer_is_never_printed(capsys):
    production.smoke("https://x", "good-key", fake_render())
    assert "Jorge" not in capsys.readouterr().out


def test_a_service_that_does_not_mask_personal_data_fails(capsys):
    client = fake_render(echo=True)
    assert not production.smoke("https://x", "good-key", client)
    out = capsys.readouterr().out
    assert "[FAIL] POST /ask con datos personales" in out
    assert production.FAKE_CURP not in out
    assert production.FAKE_EMAIL not in out


def test_a_service_that_fails_on_personal_data_does_not_pass():
    client = fake_render(pii_status=502)
    assert not production.smoke("https://x", "good-key", client)


def test_the_fake_personal_data_is_not_real():
    assert production.FAKE_EMAIL.endswith("@example.com")
    assert production.FAKE_CURP == "AAAA010101HDFBBB09"


def test_a_service_without_public_documentation_fails(capsys):
    client = fake_render(schema=None)
    assert not production.smoke("https://x", "good-key", client)
    assert "[FAIL] GET /openapi.json" in capsys.readouterr().out


def test_a_schema_missing_a_route_fails():
    client = fake_render(schema={"paths": {"/health": {}}})
    assert not production.smoke("https://x", "good-key", client)


def test_a_schema_that_is_not_json_fails_without_raising():
    client = fake_render(schema="not an object")
    assert not production.smoke("https://x", "good-key", client)


def test_the_key_must_come_from_the_environment(monkeypatch, capsys):
    monkeypatch.delenv("SMOKE_API_KEY", raising=False)
    assert production.main(["https://x"]) == 2
    assert "SMOKE_API_KEY" in capsys.readouterr().out
