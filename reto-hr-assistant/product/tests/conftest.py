"""Fixtures compartidas: arman la aplicación con dependencias inyectadas."""

import io
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import load_settings
from app.directory import EmployeeDirectory
from app.llm import ModelReply, build_model
from app.main import create_app

PRODUCT_ROOT = Path(__file__).resolve().parent.parent
EMPLOYEES_FILE = PRODUCT_ROOT / "data" / "employees.json"

# --- Sesión 4: clave de prueba generada al vuelo, nunca un literal compartido ---

TEST_CLIENT = "qa-tester"
TEST_API_KEY = secrets.token_urlsafe(24)
AUTH_HEADERS = {"X-API-Key": TEST_API_KEY}


def with_test_key(environ=None):
    """Agrega ``API_KEYS`` con la clave de prueba si la prueba no trae la suya.

    :param environ: Variables de entorno de la prueba
    :type environ: dict or None
    :return: Copia de las variables con ``API_KEYS``
    :rtype: dict
    """
    values = dict(environ or {})
    values.setdefault("API_KEYS", f"{TEST_CLIENT}:{TEST_API_KEY}")
    return values


@pytest.fixture
def api_key():
    """Clave válida del cliente de prueba.

    :return: Clave generada para esta corrida
    :rtype: str
    """
    return TEST_API_KEY


@pytest.fixture
def directory():
    """Directorio de empleados cargado desde los datos del producto.

    :return: Directorio de solo lectura
    :rtype: EmployeeDirectory
    """
    return EmployeeDirectory(EMPLOYEES_FILE)


@pytest.fixture
def make_client():
    """Fábrica de clientes HTTP con la configuración que pida cada prueba.

    :return: Función que recibe variables de entorno y devuelve un ``TestClient``
    :rtype: callable
    """

    def _make(environ=None):
        settings = load_settings(with_test_key(environ))
        employees = EmployeeDirectory(settings.employees_path)
        model = build_model(settings, employees)
        app = create_app(settings=settings, model=model, directory=employees)
        return TestClient(app, headers=AUTH_HEADERS)

    return _make


class ScriptedModel:
    """Modelo de prueba que devuelve respuestas guionadas y anota lo que recibe.

    :param replies: Textos que devolverá, en orden
    :type replies: list[str]
    """

    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = []

    def complete(self, messages):
        """Devuelve la siguiente respuesta del guion.

        :param messages: Conversación recibida
        :type messages: list[dict]
        :return: Respuesta guionada con 10 tokens de entrada y 2 de salida
        :rtype: ModelReply
        """
        self.calls.append([dict(message) for message in messages])
        text = self._replies.pop(0)
        return ModelReply(text=text, input_tokens=10, output_tokens=2)


@pytest.fixture
def scripted_model():
    """Fábrica de modelos guionados.

    :return: Función que recibe los textos del guion y devuelve un ``ScriptedModel``
    :rtype: callable
    """
    return ScriptedModel


FIXED_NOW = datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc)


class FakeClock:
    """Reloj falso: hora fija en UTC y un monotónico que avanza en cada lectura.

    :param step_seconds: Segundos que avanza ``monotonic()`` en cada llamada
    :type step_seconds: float
    """

    def __init__(self, step_seconds=0.01):
        self._step = step_seconds
        self._ticks = 0.0

    def now(self):
        """Devuelve siempre la misma hora en UTC.

        :return: Hora fija
        :rtype: datetime.datetime
        """
        return FIXED_NOW

    def monotonic(self):
        """Avanza un paso y devuelve el valor acumulado.

        :return: Segundos desde un origen arbitrario
        :rtype: float
        """
        self._ticks += self._step
        return self._ticks


@pytest.fixture
def make_clock():
    """Fábrica de relojes falsos.

    :return: Clase ``FakeClock``
    :rtype: type
    """
    return FakeClock


class ObservedApp:
    """Cliente HTTP junto con el log JSON que dejó la aplicación.

    :param client: Cliente de prueba
    :type client: fastapi.testclient.TestClient
    :param stream: Flujo donde escribe el log
    :type stream: io.StringIO
    """

    def __init__(self, client, stream):
        self.client = client
        self.stream = stream

    def log_text(self):
        """Devuelve el log completo como texto.

        :return: Todas las líneas escritas
        :rtype: str
        """
        return self.stream.getvalue()

    def events(self, name=None):
        """Devuelve los eventos del log, opcionalmente filtrados por nombre.

        :param name: Valor de ``event`` buscado; ``None`` devuelve todos
        :type name: str or None
        :return: Eventos ya interpretados como JSON
        :rtype: list[dict]
        """
        lines = [line for line in self.log_text().splitlines() if line.strip()]
        parsed = [json.loads(line) for line in lines]
        return [event for event in parsed if name is None or event["event"] == name]


@pytest.fixture
def make_observed():
    """Fábrica de aplicaciones con reloj falso y log en memoria.

    Por omisión el cliente HTTP manda la clave de prueba en ``X-API-Key``; con
    ``api_key=None`` no manda ninguna.

    :return: Función que recibe entorno, modelo, reloj y clave y devuelve
        ``ObservedApp``
    :rtype: callable
    """

    def _make(environ=None, model=None, clock=None, api_key=TEST_API_KEY):
        settings = load_settings(with_test_key(environ))
        employees = EmployeeDirectory(settings.employees_path)
        stream = io.StringIO()
        app = create_app(
            settings=settings,
            model=model or build_model(settings, employees),
            directory=employees,
            clock=clock or FakeClock(),
            log_stream=stream,
        )
        headers = {"X-API-Key": api_key} if api_key else {}
        client = TestClient(app, raise_server_exceptions=False, headers=headers)
        return ObservedApp(client, stream)

    return _make


# --- Sesión 3: modelo real a través de AI Gateway, siempre con transporte simulado ---

FAKE_TOKEN = "secret-token-xyz"
GATEWAY_ENVIRON = {
    "MODEL_PROVIDER": "gateway",
    "CF_ACCOUNT_ID": "acct-123",
    "CF_GATEWAY_ID": "hr-gateway",
    "CF_API_TOKEN": FAKE_TOKEN,
}


def _gateway_reply(
    content, prompt_tokens=12, completion_tokens=4, cache_status=None
):
    """Arma una respuesta del gateway con el formato de chat completions.

    :param content: Texto que devuelve el modelo
    :type content: str
    :param prompt_tokens: Tokens de entrada que informa ``usage``
    :type prompt_tokens: int
    :param completion_tokens: Tokens de salida que informa ``usage``
    :type completion_tokens: int
    :param cache_status: Valor de ``cf-aig-cache-status``; ``None`` no lo manda
    :type cache_status: str or None
    :return: Respuesta HTTP simulada
    :rtype: httpx.Response
    """
    headers = {"cf-aig-cache-status": cache_status} if cache_status else {}
    body = {
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        },
    }
    return httpx.Response(200, json=body, headers=headers)


@pytest.fixture
def gateway_environ():
    """Variables de entorno de un gateway falso (nunca se llama a la red).

    :return: Copia nueva de las variables
    :rtype: dict
    """
    return dict(GATEWAY_ENVIRON)


@pytest.fixture
def gateway_reply():
    """Fábrica de respuestas simuladas del gateway.

    :return: Función que arma un ``httpx.Response``
    :rtype: callable
    """
    return _gateway_reply


@pytest.fixture
def make_gateway_models():
    """Fábrica de modelos del gateway con un ``httpx.MockTransport`` inyectado.

    :return: Función que recibe entorno y manejador y devuelve
        ``(settings, directory, models)``
    :rtype: callable
    """

    def _make(environ, handler):
        from app.llm import build_models  # pylint: disable=import-outside-toplevel

        settings = load_settings(with_test_key(environ))
        employees = EmployeeDirectory(settings.employees_path)
        client = httpx.Client(transport=httpx.MockTransport(handler))
        models = build_models(settings, employees, http_client=client)
        return settings, employees, models

    return _make
