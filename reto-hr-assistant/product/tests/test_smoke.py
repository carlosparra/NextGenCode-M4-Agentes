"""Pruebas de la prueba de humo ``scripts/smoke.py``.

Contrato: ``main(argv, environ, http_client=None) -> int``. ``argv`` trae solo la
URL; la clave sale de ``environ["SMOKE_API_KEY"]``; el código de salida es 0 solo
si los tres chequeos pasan.
"""

import importlib.util
from pathlib import Path

import httpx

SMOKE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "smoke.py"
IN_PROCESS_URL = "http://testserver"


def load_smoke():
    """Carga ``scripts/smoke.py`` como módulo.

    :return: Módulo de la prueba de humo
    :rtype: types.ModuleType
    """
    spec = importlib.util.spec_from_file_location("smoke", SMOKE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_smoke_prints_three_ok_checks_against_a_healthy_service(
    make_observed, api_key, capsys
):
    service = make_observed(api_key=None)

    code = load_smoke().main(
        [IN_PROCESS_URL], {"SMOKE_API_KEY": api_key}, http_client=service.client
    )

    output = capsys.readouterr()
    assert code == 0
    assert output.out.count("[OK]") == 3
    assert "[FAIL]" not in output.out
    assert api_key not in output.out + output.err


def test_smoke_fails_when_ask_answers_without_a_key(capsys):
    always_ok = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"answer": "Hola"})
    )
    client = httpx.Client(transport=always_ok)

    code = load_smoke().main(
        ["https://hr.example"], {"SMOKE_API_KEY": "smoke-key-1234567890"}, client
    )

    output = capsys.readouterr().out
    assert code != 0
    assert output.count("[OK]") == 2
    assert output.count("[FAIL]") == 1
    assert "smoke-key-1234567890" not in output


def test_smoke_without_api_key_fails_with_a_clear_message(capsys):
    sent = []

    def record(request):
        sent.append(request)
        return httpx.Response(200)

    client = httpx.Client(transport=httpx.MockTransport(record))

    code = load_smoke().main(["https://hr.example"], {}, client)

    output = capsys.readouterr()
    assert code != 0
    assert "SMOKE_API_KEY" in output.out + output.err
    assert not sent
