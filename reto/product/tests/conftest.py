"""Fixtures compartidas: datos de prueba, configuracion, dobles y cliente HTTP."""

import io
import json
import sys
import types
from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import load_settings
from app.directory import EmployeeDirectory
from app.llm import Completion, build_llm
from app.main import create_app

EMPLOYEES = [
    {
        "id": "EMP-0001",
        "name": "Ana López",
        "department": "Tecnología",
        "role": "Analista de datos",
        "start_date": "2019-03-04",
        "status": "activo",
    },
    {
        "id": "EMP-0002",
        "name": "Luis Pérez",
        "department": "Ventas",
        "role": "Ejecutivo de cuenta",
        "start_date": "2021-07-19",
        "status": "activo",
    },
    {
        "id": "EMP-0003",
        "name": "Marta Ruiz",
        "department": "Tecnología",
        "role": "Desarrolladora",
        "start_date": "2016-11-02",
        "status": "baja",
    },
    {
        "id": "EMP-0004",
        "name": "Jorge Díaz",
        "department": "Tecnología",
        "role": "Líder técnico",
        "start_date": "2022-01-10",
        "status": "activo",
    },
    {
        "id": "EMP-0005",
        "name": "Sofía Gómez",
        "department": "Finanzas",
        "role": "Contadora",
        "start_date": "2020-05-25",
        "status": "activo",
    },
]

# Sesion 4: toda peticion a /ask y /metrics lleva la clave de este cliente.
TEST_CLIENT_NAME = "tests"
TEST_API_KEY = "tests-key-0123456789abcd"
TEST_API_KEYS = f"{TEST_CLIENT_NAME}:{TEST_API_KEY}"
API_KEY_HEADER = "X-API-Key"

TOOL_RESULT_PREFIX = "Resultado de la herramienta: "
CAP_MESSAGE = "No pude completar la respuesta. Intenta con una pregunta más concreta."
FIXED_NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


class FakeClock:
    """Reloj doble: hora fija y un contador monotono que avanza en cada lectura.

    :param step_seconds: Segundos que avanza ``monotonic()`` en cada llamada
    :type step_seconds: float
    """

    def __init__(self, step_seconds=0.25):
        self.step_seconds = step_seconds
        self.readings = 0

    def now(self):
        """Devuelve siempre la misma hora UTC.

        :return: La hora fija de las pruebas
        :rtype: datetime
        """
        return FIXED_NOW

    def monotonic(self):
        """Avanza ``step_seconds`` y devuelve el total en segundos.

        :return: Segundos acumulados
        :rtype: float
        """
        self.readings += 1
        return self.readings * self.step_seconds


class ManualClock:
    """Reloj doble que solo avanza cuando la prueba lo pide.

    Sirve para el limite de peticiones: ``FakeClock`` avanza en cada lectura.

    :param start: Segundos iniciales de ``monotonic()``
    :type start: float
    """

    def __init__(self, start=1000.0):
        self.seconds = start

    def now(self):
        """Devuelve siempre la misma hora UTC.

        :return: La hora fija de las pruebas
        :rtype: datetime
        """
        return FIXED_NOW

    def monotonic(self):
        """Devuelve los segundos actuales sin avanzar.

        :return: Segundos acumulados
        :rtype: float
        """
        return self.seconds

    def advance(self, seconds):
        """Avanza el reloj.

        :param seconds: Segundos a avanzar
        :type seconds: float
        """
        self.seconds += seconds


def read_log(stream):
    """Convierte el log escrito en el stream en una lista de eventos.

    :param stream: Buffer donde la aplicacion escribe el log
    :type stream: io.StringIO
    :return: Un diccionario por linea
    :rtype: list[dict]
    """
    return [json.loads(line) for line in stream.getvalue().splitlines() if line]


def build_client(settings, llm, directory, **dependencies):
    """Crea la app con dependencias inyectadas y devuelve su cliente HTTP.

    :param settings: Configuracion de la aplicacion
    :type settings: Settings
    :param llm: Modelo a usar
    :type llm: LLM
    :param directory: Directorio de empleados
    :type directory: EmployeeDirectory
    :param dependencies: ``clock``, ``log_stream``, ``tracer`` y, opcional,
        ``raise_server_exceptions``
    :type dependencies: dict
    :return: Cliente HTTP de prueba
    :rtype: TestClient
    """
    raise_errors = dependencies.pop("raise_server_exceptions", True)
    app = create_app(settings=settings, llm=llm, directory=directory, **dependencies)
    return keyed_client(app, raise_server_exceptions=raise_errors)


def keyed_client(app, **options):
    """Cliente HTTP que manda la clave de prueba en cada peticion.

    :param app: Aplicacion a probar
    :type app: fastapi.FastAPI
    :param options: Opciones extra de ``TestClient``
    :type options: dict
    :return: Cliente HTTP de prueba con ``X-API-Key``
    :rtype: TestClient
    """
    return TestClient(app, headers={API_KEY_HEADER: TEST_API_KEY}, **options)


class RecordingTracer:  # pylint: disable=too-few-public-methods
    """Trazador doble que anota las opciones de cada traza."""

    def __init__(self):
        self.spans = []

    def trace(self, func, **options):
        """Anota las opciones y devuelve la funcion sin cambios.

        :param func: Funcion a trazar
        :type func: callable
        :param options: ``name``, ``request_id``, ``client``, ``model``...
        :type options: dict
        :return: La misma funcion
        :rtype: callable
        """
        self.spans.append(options)
        return func


def fake_langsmith_module(recorded):
    """Modulo ``langsmith`` falso que registra cliente y decoradores.

    :param recorded: Diccionario donde se guardan los argumentos recibidos
    :type recorded: dict
    :return: Modulo que sustituye a ``langsmith`` en ``sys.modules``
    :rtype: types.ModuleType
    """
    module = types.ModuleType("langsmith")

    class Client:  # pylint: disable=too-few-public-methods
        """Cliente falso: guarda sus argumentos y no se conecta."""

        def __init__(self, **kwargs):
            recorded["client"] = kwargs

    def traceable(*_args, **kwargs):
        recorded.setdefault("traceable", []).append(kwargs)
        return lambda func: func

    module.Client = Client
    module.traceable = traceable
    return module


def langsmith_settings(employees_file, monkeypatch, recorded):
    """Configuracion con trazas de LangSmith activas y el modulo falso instalado.

    :param employees_file: Archivo temporal de empleados
    :type employees_file: pathlib.Path
    :param monkeypatch: Fixture de pytest para sustituir ``sys.modules``
    :type monkeypatch: pytest.MonkeyPatch
    :param recorded: Diccionario donde el modulo falso guarda lo que recibe
    :type recorded: dict
    :return: Configuracion con ``LANGSMITH_TRACING`` y clave de prueba
    :rtype: Settings
    """
    monkeypatch.setitem(sys.modules, "langsmith", fake_langsmith_module(recorded))
    return load_settings(
        {
            "EMPLOYEES_PATH": str(employees_file),
            "LANGSMITH_TRACING": "true",
            "LANGSMITH_API_KEY": "lsv2-test-key",
        }
    )


def build_default_app(make_settings, directory, clock, log_stream, **dependencies):
    """App con los modelos simulados que arma la propia aplicacion (con precio).

    :param make_settings: Fabrica de configuracion de la fixture ``make_settings``
    :type make_settings: callable
    :param directory: Directorio de empleados
    :type directory: EmployeeDirectory
    :param clock: Reloj de la aplicacion
    :type clock: FakeClock
    :param log_stream: Buffer donde la aplicacion escribe su log
    :type log_stream: io.StringIO
    :param dependencies: ``env`` (variables extra) y dependencias de
        ``create_app`` como ``tracer`` o ``rate_limiter``
    :type dependencies: dict
    :return: Aplicacion lista para probar
    :rtype: fastapi.FastAPI
    """
    env = dependencies.pop("env", {})
    return create_app(
        settings=make_settings(**env),
        directory=directory,
        clock=clock,
        log_stream=log_stream,
        **dependencies,
    )


class ScriptedLLM:
    """Modelo doble que devuelve textos fijos y guarda lo que recibe.

    Cuando se acaban los textos, repite el ultimo.

    :param texts: Respuestas del modelo, en orden
    :type texts: list[str]
    :param input_tokens: Tokens de entrada que reporta cada llamada
    :type input_tokens: int
    :param output_tokens: Tokens de salida que reporta cada llamada
    :type output_tokens: int
    """

    def __init__(self, texts, input_tokens=1, output_tokens=1):
        self.texts = list(texts)
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.calls = []

    def complete(self, messages):
        """Devuelve la siguiente respuesta guionizada.

        :param messages: Conversacion enviada por el agente
        :type messages: list[dict]
        :return: La respuesta del modelo con sus tokens
        :rtype: Completion
        """
        self.calls.append([dict(message) for message in messages])
        index = min(len(self.calls) - 1, len(self.texts) - 1)
        return Completion(
            text=self.texts[index],
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
        )


@pytest.fixture
def employees_file(tmp_path):
    """Archivo temporal con los cinco empleados de la especificacion."""
    path = tmp_path / "employees.json"
    path.write_text(json.dumps(EMPLOYEES, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture
def settings(employees_file):
    """Configuracion por omision apuntando al archivo temporal."""
    return load_settings(
        {"EMPLOYEES_PATH": str(employees_file), "API_KEYS": TEST_API_KEYS}
    )


@pytest.fixture
def directory(employees_file):
    """Directorio de empleados cargado desde el archivo temporal."""
    return EmployeeDirectory(employees_file)


@pytest.fixture
def fake_llm(settings, directory):
    """El modelo simulado construido como lo hace la aplicacion."""
    return build_llm(settings, directory)


@pytest.fixture
def clock():
    """Reloj falso que avanza 250 ms por lectura."""
    return FakeClock()


@pytest.fixture
def log_stream():
    """Buffer donde la aplicacion escribe su log JSON."""
    return io.StringIO()


@pytest.fixture
def client(settings, fake_llm, directory, clock, log_stream):
    """Cliente HTTP con el modelo simulado, el reloj falso y el log en memoria."""
    return build_client(
        settings, fake_llm, directory, clock=clock, log_stream=log_stream
    )


# Sesion 3: costos.
SMALL_MODEL = "@cf/meta/llama-3.1-8b-instruct-fast"
LARGE_MODEL = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
PRICES = {
    "currency": "USD",
    "unit": "per million tokens",
    "models": {
        "fake": {"input": 0.0, "output": 0.0},
        SMALL_MODEL: {"input": 0.045, "output": 0.384},
        LARGE_MODEL: {"input": 0.293, "output": 2.253},
    },
}
CF_TOKEN = "cf-very-secret-token"
GATEWAY_ENV = {
    "MODEL_PROVIDER": "gateway",
    "CF_ACCOUNT_ID": "acc-1",
    "CF_GATEWAY_ID": "gw-1",
    "CF_API_TOKEN": CF_TOKEN,
}


BASE_FIELDS = {
    "answer",
    "steps",
    "tools_used",
    "input_tokens",
    "output_tokens",
    "request_id",
}


def gateway_client(make_settings, directory, clock, log_stream, transport):
    """Crea la app con el modelo de gateway y un cliente HTTP falso.

    :param make_settings: Fabrica de configuracion de la fixture ``make_settings``
    :type make_settings: callable
    :param directory: Directorio de empleados
    :type directory: EmployeeDirectory
    :param clock: Reloj de la aplicacion
    :type clock: FakeClock
    :param log_stream: Buffer donde la aplicacion escribe su log
    :type log_stream: io.StringIO
    :param transport: Transporte de ``httpx`` sin red
    :type transport: httpx.MockTransport
    :return: Cliente HTTP de prueba
    :rtype: TestClient
    """
    app = create_app(
        settings=make_settings(**GATEWAY_ENV),
        directory=directory,
        clock=clock,
        log_stream=log_stream,
        http_client=httpx.Client(transport=transport),
    )
    return keyed_client(app)


@pytest.fixture
def prices_file(tmp_path):
    """Archivo temporal con los precios de ``spec/model_prices.json``."""
    path = tmp_path / "model_prices.json"
    path.write_text(json.dumps(PRICES), encoding="utf-8")
    return path


@pytest.fixture
def make_settings(employees_file, prices_file):
    """Fabrica de configuracion con los archivos temporales y variables extra.

    :return: Funcion que recibe variables de entorno y devuelve ``Settings``
    :rtype: callable
    """

    def factory(**env):
        base = {
            "EMPLOYEES_PATH": str(employees_file),
            "PRICES_PATH": str(prices_file),
            "API_KEYS": TEST_API_KEYS,
        }
        return load_settings({**base, **env})

    return factory
