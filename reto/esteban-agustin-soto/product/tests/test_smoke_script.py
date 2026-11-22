"""Pruebas de ``scripts/smoke.py`` contra un servidor simulado (sin red).

El script no está en un paquete: se carga por ruta con ``importlib``, sin
tocar ``sys.path``.
"""

import importlib.util
import json
from pathlib import Path

import httpx
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "smoke.py"

SERVICE_URL = "https://servicio-ficticio.example"
API_KEY = "clave-ficticia-0123456789"
CURP = "AAAA010101HDFBBB09"
EMAIL = "persona.prueba@example.com"
GOOD_ANSWER = "Según el directorio: Jorge Díaz, Tecnología"
SAFE_ANSWER = "No puedo confirmar datos personales."
FAILURE_ANSWER = "No pude completar la respuesta. Intenta con otra pregunta."
GOOD_SCHEMA = {"paths": {"/health": {}, "/ask": {}, "/metrics": {}}}


@pytest.fixture(name="smoke_module", scope="module")
def smoke_module_fixture():
    """Carga ``scripts/smoke.py`` como módulo, sin convertir ``scripts/`` en paquete.

    :return: Módulo del script de la prueba de humo
    :rtype: types.ModuleType
    """
    spec = importlib.util.spec_from_file_location("smoke_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_handler(seen, **options):
    """Arma el manejador que simula el servicio publicado.

    Opciones, todas opcionales: ``health`` (código de ``/health``), ``schema``
    (cuerpo de ``/openapi.json``; ``None`` da 404 y ``bytes`` se envía en
    crudo), ``anonymous`` (código de ``/ask`` sin clave), ``ask_status``,
    ``answer`` (campo ``answer`` con clave), ``pii_status`` y ``pii_answer``
    (código y texto para la pregunta con datos personales).

    :param seen: Lista donde se guarda cada petición recibida, en orden
    :type seen: list
    :param options: Opciones del servicio simulado
    :type options: object
    :return: Función para ``httpx.MockTransport``
    :rtype: collections.abc.Callable
    """
    def handler(request):
        seen.append(request)
        path = request.url.path
        if path == "/health":
            return httpx.Response(options.get("health", 200))
        if path == "/openapi.json":
            return docs_response(options.get("schema", GOOD_SCHEMA))
        return ask_response(request, options)

    return handler


def docs_response(schema):
    """Simula ``/openapi.json``.

    :param schema: ``None`` para 404, ``bytes`` para un cuerpo en crudo o un
        diccionario para un JSON
    :type schema: dict | bytes | None
    :return: Respuesta simulada
    :rtype: httpx.Response
    """
    if schema is None:
        return httpx.Response(404)
    if isinstance(schema, bytes):
        return httpx.Response(200, content=schema)
    return httpx.Response(200, json=schema)


def ask_response(request, options):
    """Simula ``POST /ask``, con o sin clave y con o sin datos personales.

    :param request: Petición recibida
    :type request: httpx.Request
    :param options: Opciones del servicio simulado
    :type options: dict
    :return: Respuesta simulada
    :rtype: httpx.Response
    """
    if request.headers.get("X-API-Key") != API_KEY:
        return httpx.Response(options.get("anonymous", 401))
    if CURP in json.loads(request.content)["question"]:
        status = options.get("pii_status", 200)
        reply = options.get("pii_answer", SAFE_ANSWER)
    else:
        status = options.get("ask_status", 200)
        reply = options.get("answer", GOOD_ANSWER)
    return httpx.Response(status, json={"answer": reply})


def run_smoke(module, capsys, **options):
    """Corre ``smoke()`` contra el servicio simulado y recoge lo que imprime.

    :param module: Módulo del script de la prueba de humo
    :type module: types.ModuleType
    :param capsys: Fixture que captura la salida
    :type capsys: pytest.CaptureFixture
    :param options: Opciones del servicio simulado
    :type options: object
    :return: Resultado, texto impreso y peticiones recibidas
    :rtype: tuple
    """
    seen = []
    transport = httpx.MockTransport(make_handler(seen, **options))
    client = httpx.Client(transport=transport)
    passed = module.smoke(SERVICE_URL, API_KEY, client)
    return passed, capsys.readouterr().out, seen


def patch_client(monkeypatch, module, handler):
    """Hace que ``main()`` use un servidor simulado en lugar de la red.

    :param monkeypatch: Fixture para reemplazar atributos
    :type monkeypatch: pytest.MonkeyPatch
    :param module: Módulo del script de la prueba de humo
    :type module: types.ModuleType
    :param handler: Manejador del transporte simulado
    :type handler: collections.abc.Callable
    """
    # Se guarda la clase real antes de reemplazarla
    real_client = httpx.Client
    monkeypatch.setattr(
        module.httpx,
        "Client",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(handler), **kwargs
        ),
    )


def test_healthy_service_passes_with_six_ok_lines(monkeypatch, smoke_module, capsys):
    monkeypatch.setenv("SMOKE_API_KEY", API_KEY)
    patch_client(monkeypatch, smoke_module, make_handler([]))
    assert smoke_module.main([SERVICE_URL]) == 0
    out = capsys.readouterr().out
    assert out.count("[OK]") == 6
    assert "[FAIL]" not in out


def test_health_is_the_first_request(smoke_module, capsys):
    _, _, seen = run_smoke(smoke_module, capsys)
    assert seen[0].url.path == "/health"


@pytest.mark.parametrize(
    "schema",
    [
        None,
        {"paths": {"/health": {}}},
        {"paths": {"/ask": {}}},
        b"<html>no es JSON</html>",
    ],
    ids=["missing-docs", "no-ask-path", "no-health-path", "not-json"],
)
def test_incomplete_documentation_fails(smoke_module, capsys, schema):
    passed, out, _ = run_smoke(smoke_module, capsys, schema=schema)
    assert passed is False
    assert out.count("[FAIL]") == 1


def test_ask_without_key_must_be_rejected_with_401(smoke_module, capsys):
    passed, out, _ = run_smoke(smoke_module, capsys, anonymous=200)
    assert passed is False
    assert out.count("[FAIL]") == 1


def test_ask_with_key_must_answer_200(smoke_module, capsys):
    passed, out, _ = run_smoke(smoke_module, capsys, ask_status=500)
    assert passed is False
    assert "[FAIL]" in out


def test_answer_without_the_employee_fails(smoke_module, capsys):
    passed, out, _ = run_smoke(smoke_module, capsys, answer="Pregunta por EMP-0001.")
    assert passed is False
    assert out.count("[FAIL]") == 1


def test_fixed_failure_message_fails_even_with_status_200(smoke_module, capsys):
    answer = f"{FAILURE_ANSWER} Jorge Díaz"
    passed, out, _ = run_smoke(smoke_module, capsys, answer=answer)
    assert passed is False
    assert out.count("[FAIL]") == 1


@pytest.mark.parametrize(
    "leak",
    [f"Tu CURP es {CURP}", f"Tu correo es {EMAIL}", f"{CURP.lower()} {EMAIL.upper()}"],
    ids=["curp", "email", "other-letter-case"],
)
def test_personal_data_in_the_answer_fails(smoke_module, capsys, leak):
    passed, out, _ = run_smoke(smoke_module, capsys, pii_answer=leak)
    assert passed is False
    assert out.count("[FAIL]") == 1


def test_error_on_the_personal_data_question_fails(smoke_module, capsys):
    passed, out, _ = run_smoke(smoke_module, capsys, pii_status=502)
    assert passed is False
    assert out.count("[FAIL]") == 1


def test_output_never_shows_the_answer_nor_secrets(smoke_module, capsys):
    leaky = f"Jorge Díaz {CURP} {EMAIL} texto-del-servicio"
    _, out, _ = run_smoke(smoke_module, capsys, answer=leaky, pii_answer=leaky)
    shown = out.lower()
    for secret in (CURP, EMAIL, API_KEY, "texto-del-servicio"):
        assert secret.lower() not in shown


@pytest.mark.parametrize(
    ("args", "key"),
    [([SERVICE_URL], ""), ([], API_KEY), ([""], API_KEY)],
    ids=["no-key", "no-url", "empty-url"],
)
def test_missing_key_or_url_exits_with_2(monkeypatch, smoke_module, capsys, args, key):
    monkeypatch.setenv("SMOKE_API_KEY", key)
    assert smoke_module.main(args) == 2
    out = capsys.readouterr().out
    assert "SMOKE_API_KEY" in out
    assert API_KEY not in out
    assert SERVICE_URL not in out


def test_network_error_fails_and_prints_only_the_class_name(
    monkeypatch, smoke_module, capsys
):
    def unreachable(request):
        raise httpx.ConnectError(f"detalle-privado {API_KEY} {request.url}")

    monkeypatch.setenv("SMOKE_API_KEY", API_KEY)
    patch_client(monkeypatch, smoke_module, unreachable)
    assert smoke_module.main([SERVICE_URL]) == 1
    out = capsys.readouterr().out
    assert "ConnectError" in out
    for hidden in (API_KEY, SERVICE_URL, "detalle-privado"):
        assert hidden not in out
