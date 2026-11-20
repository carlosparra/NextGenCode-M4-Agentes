"""Pruebas de la prueba de humo ``scripts/smoke.py`` (spec/04-production.md, punto 8).

Ninguna prueba toca la red: el servicio se simula con ``httpx.MockTransport``.
La espera entre intentos de ``/health`` se reemplaza por una función que solo
anota los segundos pedidos, para que las pruebas no duerman. La clave es falsa.
"""

import httpx
import pytest

from scripts import smoke

FAKE_KEY = "smoke-fake-key-not-real-0001"
BASE_URL = "https://hr-assistant.example.test"


class FakeService:
    """Servicio simulado que responde como el HR Assistant publicado.

    :param health_statuses: Códigos que devuelve ``/health``, en orden; el
        último se repite. ``None`` simula un error de transporte
    :type health_statuses: list[int or None]
    :param valid_key: Clave que acepta ``/ask``
    :type valid_key: str
    :param ask_without_key: Código de ``/ask`` sin clave
    :type ask_without_key: int
    :param ask_down: Si es ``True``, ``/ask`` falla con error de transporte
    :type ask_down: bool
    """

    def __init__(self, health_statuses=(200,), valid_key=FAKE_KEY,
                 ask_without_key=401, ask_down=False):
        self.health_statuses = list(health_statuses)
        self.valid_key = valid_key
        self.ask_without_key = ask_without_key
        self.ask_down = ask_down
        self.requests = []

    def handle(self, request):
        """Responde una petición simulada.

        :param request: Petición recibida
        :type request: httpx.Request
        :return: Respuesta simulada
        :rtype: httpx.Response
        """
        self.requests.append(request)
        if request.url.path == "/health":
            status = self.health_statuses[0]
            if len(self.health_statuses) > 1:
                self.health_statuses.pop(0)
            if status is None:
                raise httpx.ConnectError("servicio dormido", request=request)
            return httpx.Response(status, json={"status": "ok"})
        if self.ask_down:
            raise httpx.ConnectError("servicio caído", request=request)
        key = request.headers.get(smoke.API_KEY_HEADER)
        if key is None:
            return httpx.Response(self.ask_without_key)
        if key == self.valid_key:
            return httpx.Response(200, json={"answer": "EMP-0004"})
        return httpx.Response(401)

    def client(self):
        """Cliente ``httpx`` conectado a este servicio simulado.

        :return: Cliente con transporte simulado
        :rtype: httpx.Client
        """
        return httpx.Client(transport=httpx.MockTransport(self.handle))


@pytest.fixture(autouse=True)
def sleeps(monkeypatch):
    """Reemplaza ``time.sleep`` del script y devuelve los segundos pedidos."""
    recorded = []
    monkeypatch.setattr(smoke.time, "sleep", recorded.append)
    return recorded


def run_main(capsys, service, args=(BASE_URL,), environ=None):
    """Corre ``main`` con el servicio simulado y devuelve código y salida.

    :return: Tupla ``(código, salida impresa)``
    :rtype: tuple[int, str]
    """
    environ = {smoke.KEY_VARIABLE: FAKE_KEY} if environ is None else environ
    code = smoke.main(list(args), environ=environ, client=service.client())
    return code, capsys.readouterr().out


def test_healthy_service_passes_all_checks_and_exits_zero(capsys):
    code, output = run_main(capsys, FakeService())
    assert code == smoke.EXIT_OK
    assert output.count("[OK]") == 3
    assert "[FAIL]" not in output


def test_rejected_key_prints_fail_and_exits_one(capsys):
    code, output = run_main(capsys, FakeService(valid_key="another-fake-key"))
    assert code == smoke.EXIT_FAIL
    assert "[FAIL] POST /ask con clave -> 401 (esperado 200)" in output


def test_service_that_accepts_requests_without_key_fails(capsys):
    code, output = run_main(capsys, FakeService(ask_without_key=200))
    assert code == smoke.EXIT_FAIL
    assert "[FAIL] POST /ask sin clave -> 200 (esperado 401)" in output


def test_missing_url_is_a_usage_error(capsys):
    service = FakeService()
    code, output = run_main(capsys, service, args=())
    assert code == smoke.EXIT_USAGE
    assert "Uso:" in output
    assert not service.requests


def test_extra_arguments_are_a_usage_error(capsys):
    code, output = run_main(capsys, FakeService(), args=(BASE_URL, FAKE_KEY))
    assert code == smoke.EXIT_USAGE
    assert FAKE_KEY not in output


@pytest.mark.parametrize("environ", [{}, {smoke.KEY_VARIABLE: "   "}])
def test_missing_smoke_api_key_is_a_usage_error(capsys, environ):
    service = FakeService()
    code, output = run_main(capsys, service, environ=environ)
    assert code == smoke.EXIT_USAGE
    assert smoke.KEY_VARIABLE in output
    assert not service.requests


@pytest.mark.parametrize("service", [
    FakeService(),
    FakeService(valid_key="another-fake-key"),
    FakeService(health_statuses=(None,), ask_down=True),
])
def test_key_is_never_printed(capsys, service):
    _, output = run_main(capsys, service)
    assert FAKE_KEY not in output


def test_key_is_sent_only_in_the_api_key_header():
    service = FakeService()
    smoke.run_checks(service.client(), BASE_URL + "/", FAKE_KEY, wait=0)
    ask_requests = [r for r in service.requests if r.url.path == "/ask"]
    sent_keys = [r.headers.get(smoke.API_KEY_HEADER) for r in ask_requests]
    assert sent_keys == [None, FAKE_KEY]
    assert all(FAKE_KEY not in str(r.url) for r in service.requests)


def test_trailing_slash_in_url_is_ignored():
    service = FakeService()
    assert smoke.run_checks(service.client(), BASE_URL + "/", FAKE_KEY, wait=0)
    assert {str(r.url) for r in service.requests} == {
        f"{BASE_URL}/health", f"{BASE_URL}/ask",
    }


def test_health_is_retried_until_the_service_wakes_up(sleeps):
    service = FakeService(health_statuses=(None, 503, 200))
    status = smoke.wait_for_health(service.client(), BASE_URL, attempts=5, wait=7)
    assert status == 200
    assert sleeps == [7, 7]


def test_health_returns_last_status_after_all_attempts(sleeps):
    service = FakeService(health_statuses=(503,))
    status = smoke.wait_for_health(service.client(), BASE_URL, attempts=3, wait=1)
    assert status == 503
    assert len(sleeps) == 2


def test_health_transport_error_reports_status_zero():
    service = FakeService(health_statuses=(None,))
    assert smoke.wait_for_health(service.client(), BASE_URL, attempts=2, wait=0) == 0


def test_ask_transport_error_is_reported_as_fail(capsys):
    service = FakeService(ask_down=True)
    assert not smoke.run_checks(service.client(), BASE_URL, FAKE_KEY, wait=0)
    output = capsys.readouterr().out
    assert "[OK] GET /health -> 200" in output
    assert "[FAIL] POST /ask sin clave -> 0 (esperado 401)" in output
    assert "[FAIL] POST /ask con clave -> 0 (esperado 200)" in output
