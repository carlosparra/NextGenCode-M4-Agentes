"""Shared fixtures for the HR Assistant tests.

Assumed interfaces (the developer must follow them):

- ``app.config.load_settings(env: Mapping[str, str]) -> Settings`` raises
  ``ValueError`` on invalid values. ``Settings`` has ``model_provider``,
  ``agent_max_steps``, ``max_question_chars`` and ``employees_path``.
- ``app.directory.EmployeeDirectory(path)`` with ``get_employee(id)``
  (dict or None), ``search_by_department(name)`` (list) and ``departments()``.
- ``app.llm.FakeModel(departments)`` with ``complete(messages) -> str`` (JSON).
- ``app.agent.Agent(model=, directory=, max_steps=)`` with
  ``run(question, history=None)`` returning an object (or dict) with
  ``answer``, ``steps``, ``tools_used``, ``input_tokens``, ``output_tokens``.
- ``app.main.create_app(settings=, model=, directory=)``.
"""

import io
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# pylint: disable=wrong-import-position
from app.config import load_settings  # noqa: E402
from app.directory import EmployeeDirectory  # noqa: E402
from app.llm import FakeModel  # noqa: E402
from app.main import create_app  # noqa: E402
from app.observability import JsonLogger  # noqa: E402

EMPLOYEES = [
    {"id": "EMP-0001", "name": "Ana Lopez", "department": "Tecnología",
     "role": "Analista", "start_date": "2019-03-04", "status": "activo"},
    {"id": "EMP-0002", "name": "Luis Perez", "department": "Ventas",
     "role": "Ejecutivo", "start_date": "2021-07-19", "status": "activo"},
    {"id": "EMP-0003", "name": "Marta Ruiz", "department": "Tecnología",
     "role": "Desarrolladora", "start_date": "2016-11-02", "status": "baja"},
    {"id": "EMP-0004", "name": "Jorge Diaz", "department": "Tecnología",
     "role": "Lider tecnico", "start_date": "2022-01-10", "status": "activo"},
    {"id": "EMP-0005", "name": "Sofia Gomez", "department": "Finanzas",
     "role": "Contadora", "start_date": "2020-05-25", "status": "activo"},
]


ANA_KEY = "ana-key-0123456789abcdef"
BOB_KEY = "bob-key-0123456789abcdef"
API_KEYS_ENV = f"ana:{ANA_KEY},bob:{BOB_KEY}"
AUTH_HEADERS = {"X-API-Key": ANA_KEY}


class ScriptedModel:
    """Modelo simulado que repite respuestas fijas y registra sus llamadas.

    :param replies: Respuestas que se devuelven en orden (la última se repite).
    :type replies: list
    """

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def complete(self, messages):
        """Devuelve la siguiente respuesta del guion (la última se repite).

        :param messages: Mensajes que recibe el modelo.
        :type messages: list
        :return: Texto de la respuesta.
        :rtype: str
        """
        self.calls.append([dict(message) for message in messages])
        if len(self.replies) > 1:
            return self.replies.pop(0)
        return self.replies[0]


def field(result, name):
    """Lee ``name`` de un resultado que puede ser un dict o un objeto.

    :param result: Resultado del agente.
    :type result: dict | object
    :param name: Nombre del campo a leer.
    :type name: str
    :return: Valor del campo.
    :rtype: object
    """
    if isinstance(result, dict):
        return result[name]
    return getattr(result, name)


def tool_call(name, **args):
    """Construye el JSON que un modelo devuelve para pedir una herramienta.

    :param name: Nombre de la herramienta.
    :type name: str
    :param args: Argumentos de la herramienta.
    :type args: dict
    :return: Texto JSON de la petición.
    :rtype: str
    """
    return json.dumps({"tool": name, "args": args})


def answer_json(text):
    """Construye el JSON que un modelo devuelve para responder.

    :param text: Texto de la respuesta.
    :type text: str
    :return: Texto JSON de la respuesta.
    :rtype: str
    """
    return json.dumps({"answer": text})


class FakeClock:
    """Reloj determinista: cada lectura avanza ``step_ms``.

    :param step_ms: Milisegundos que avanza el reloj en cada lectura.
    :type step_ms: int
    """

    def __init__(self, step_ms=10):
        self._current = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self._step = timedelta(milliseconds=step_ms)

    def now(self):
        """Devuelve el instante actual (con zona horaria UTC) y avanza.

        :return: Instante actual.
        :rtype: datetime.datetime
        """
        value = self._current
        self._current += self._step
        return value


class RecordingLogger:
    """Logger double that keeps ``(event, fields)`` pairs in memory."""

    def __init__(self):
        self.events = []

    def log(self, event, **fields):
        """Registra un evento.

        :param event: Nombre del evento.
        :type event: str
        :param fields: Campos del evento.
        :type fields: dict
        """
        self.events.append((event, fields))

    def named(self, event):
        """Devuelve los campos de cada evento registrado llamado ``event``.

        :param event: Nombre del evento.
        :type event: str
        :return: Campos de cada evento con ese nombre.
        :rtype: list
        """
        return [fields for name, fields in self.events if name == event]


@pytest.fixture(name="make_observed_client")
def make_observed_client_fixture(employees_path, directory):
    """Fábrica de ``(client, stream)``; ``stream`` guarda la bitácora JSON.

    :param employees_path: Archivo temporal de empleados.
    :type employees_path: pathlib.Path
    :param directory: Directorio de empleados.
    :type directory: app.directory.EmployeeDirectory
    :return: Función que construye el cliente y el flujo de la bitácora.
    :rtype: collections.abc.Callable

    Interfaces de la sesión 2 (el desarrollador debe respetarlas):

    - ``app.observability.Clock`` with ``now()`` returning an aware UTC datetime.
    - ``app.observability.JsonLogger(service, clock, stream=None)`` with
      ``log(event, **fields)``; the ``request_id`` comes from
      ``app.observability.request_id_var`` (a ``ContextVar``).
    - ``app.observability.MetricsCollector(slo_p95_ms)`` with
      ``record(latency_ms, status)``, ``add_tokens(input_tokens, output_tokens)``
      and ``snapshot()`` (every ``/metrics`` field except ``pid``).
    - ``app.tracing.traced(func, name, *, enabled, api_key, hide_inputs,
      hide_outputs)`` and the module attribute ``app.tracing.traceable``.
    - ``Agent(..., logger=None)`` and
      ``create_app(settings=, model=, directory=, clock=, logger=)``.
    """

    def build(model=None, env=None, clock=None):
        values = {
            "MODEL_PROVIDER": "fake",
            "EMPLOYEES_PATH": str(employees_path),
            "API_KEYS": API_KEYS_ENV,
            "RATE_LIMIT_PER_MINUTE": "1000",
        }
        values.update(env or {})
        settings = load_settings(values)
        clock = clock or FakeClock()
        stream = io.StringIO()
        logger = JsonLogger(
            settings.service_name, clock, stream, masking=settings.pii_masking
        )
        chosen = model or FakeModel(directory.departments())
        app = create_app(
            settings=settings, model=chosen, directory=directory,
            clock=clock, logger=logger,
        )
        return TestClient(
            app, raise_server_exceptions=False, headers=AUTH_HEADERS
        ), stream

    return build


PRICES = {
    "models": {
        "fake": {"input": 0.0, "output": 0.0},
        "small-model": {"input": 1.0, "output": 2.0},
        "large-model": {"input": 10.0, "output": 20.0},
    }
}

GATEWAY_ENV = {
    "MODEL_PROVIDER": "gateway",
    "CF_ACCOUNT_ID": "acct",
    "CF_GATEWAY_ID": "gw",
    "CF_API_TOKEN": "tok",
    "MODEL_SMALL": "small-model",
    "MODEL_LARGE": "large-model",
}


def gateway_reply(text='{"answer": "ok"}', prompt=100, completion=50,
                  cache_status="MISS"):
    """Construye un ``httpx.Response`` como el que devuelve AI Gateway.

    :param text: Contenido de la respuesta del modelo.
    :type text: str
    :param prompt: Tokens de entrada.
    :type prompt: int
    :param completion: Tokens de salida.
    :type completion: int
    :param cache_status: Valor de la cabecera ``cf-aig-cache-status``.
    :type cache_status: str
    :return: Respuesta HTTP simulada.
    :rtype: httpx.Response
    """
    import httpx  # pylint: disable=import-outside-toplevel

    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"role": "assistant", "content": text}}],
            "usage": {"prompt_tokens": prompt, "completion_tokens": completion},
        },
        headers={"cf-aig-cache-status": cache_status},
    )


@pytest.fixture(name="prices_path")
def prices_path_fixture(tmp_path):
    """Tabla de precios con los nombres de modelo de las pruebas de costos.

    :param tmp_path: Carpeta temporal de la prueba.
    :type tmp_path: pathlib.Path
    :return: Ruta del archivo de precios.
    :rtype: pathlib.Path

    Interfaz asumida para la sesión 3 (el desarrollador debe respetarla):

    - ``Settings`` adds ``cf_account_id``, ``cf_gateway_id``, ``cf_api_token``,
      ``model_small``, ``model_large``, ``routing``, ``router_max_chars``,
      ``history_window``, ``model_max_tokens``, ``model_temperature``,
      ``cache_ttl_seconds`` and ``prices_path``.
    - ``app.router.choose_model(question, settings) -> (model, reason)``.
    - ``app.pricing.PriceTable(path)`` with
      ``cost(model, input_tokens, output_tokens, cached) -> float``; a bad
      file or an unknown model raises ``ValueError``.
    - ``app.llm.Completion(text, input_tokens, output_tokens, cached)``,
      ``app.llm.ModelUnavailable`` and
      ``app.llm.GatewayModel(name, settings, client=None)`` with
      ``generate(messages)``; ``client`` is an ``httpx.Client``.
    - ``FakeModel(departments, name="fake")`` and
      ``create_app(..., models={name: model})``; without ``models`` the app
      builds them from the settings. The price table is read from
      ``settings.prices_path``.
    - ``Agent(..., history_window=6)``; its result has ``calls`` (a list of
      records with ``input_tokens``, ``output_tokens`` and ``cached``).
    - ``MetricsCollector.add_cost(usd)`` and ``cost_usd`` in ``snapshot()``.
    """
    path = tmp_path / "model_prices.json"
    path.write_text(json.dumps(PRICES), encoding="utf-8")
    return path


@pytest.fixture(name="make_costs_client")
def make_costs_client_fixture(employees_path, directory, prices_path):
    """Fábrica de ``(client, stream)`` con modelos pequeño y grande con nombre.

    Con ``handler`` los modelos son ``GatewayModel`` que hablan con ese
    manejador de ``httpx.MockTransport``; con ``models`` (diccionario
    ``nombre -> modelo``) se usan esos; si no, los modelos simulados.

    :param employees_path: Archivo temporal de empleados.
    :type employees_path: pathlib.Path
    :param directory: Directorio de empleados.
    :type directory: app.directory.EmployeeDirectory
    :param prices_path: Archivo de precios.
    :type prices_path: pathlib.Path
    :return: Función que construye el cliente y el flujo de la bitácora.
    :rtype: collections.abc.Callable
    """

    def build(env=None, handler=None, models=None):
        # pylint: disable=import-outside-toplevel
        import httpx
        from app.llm import GatewayModel

        values = {
            "MODEL_PROVIDER": "fake",
            "EMPLOYEES_PATH": str(employees_path),
            "PRICES_PATH": str(prices_path),
            "MODEL_SMALL": "small-model",
            "MODEL_LARGE": "large-model",
            "API_KEYS": API_KEYS_ENV,
            "RATE_LIMIT_PER_MINUTE": "1000",
        }
        values.update(env or {})
        if handler is not None:
            values.update({k: v for k, v in GATEWAY_ENV.items()
                           if k not in (env or {})})
        settings = load_settings(values)
        clock = FakeClock()
        stream = io.StringIO()
        logger = JsonLogger(
            settings.service_name, clock, stream, masking=settings.pii_masking
        )
        if handler is not None:
            http = httpx.Client(transport=httpx.MockTransport(handler))
            models = {
                name: GatewayModel(name, settings, client=http)
                for name in (settings.model_small, settings.model_large)
            }
        app = create_app(
            settings=settings, models=models, directory=directory,
            clock=clock, logger=logger,
        )
        return TestClient(
            app, raise_server_exceptions=False, headers=AUTH_HEADERS
        ), stream

    return build


def log_lines(stream):
    """Interpreta cada línea JSON escrita en ``stream``.

    :param stream: Flujo con la bitácora.
    :type stream: io.StringIO
    :return: Una entrada por línea.
    :rtype: list
    """
    return [json.loads(line) for line in stream.getvalue().splitlines() if line]


@pytest.fixture(name="employees_path")
def employees_path_fixture(tmp_path):
    """Archivo temporal de empleados con cinco empleados conocidos.

    :param tmp_path: Carpeta temporal de la prueba.
    :type tmp_path: pathlib.Path
    :return: Ruta del archivo.
    :rtype: pathlib.Path
    """
    path = tmp_path / "employees.json"
    path.write_text(json.dumps(EMPLOYEES), encoding="utf-8")
    return path


@pytest.fixture(name="directory")
def directory_fixture(employees_path):
    """Directorio de empleados cargado del archivo temporal.

    :param employees_path: Archivo temporal de empleados.
    :type employees_path: pathlib.Path
    :return: Directorio cargado.
    :rtype: app.directory.EmployeeDirectory
    """
    return EmployeeDirectory(employees_path)


@pytest.fixture(name="make_client")
def make_client_fixture(employees_path, directory):
    """Fábrica de clientes de prueba con modelo y límites opcionales.

    :param employees_path: Archivo temporal de empleados.
    :type employees_path: pathlib.Path
    :param directory: Directorio de empleados.
    :type directory: app.directory.EmployeeDirectory
    :return: Función que construye el cliente.
    :rtype: collections.abc.Callable
    """

    def build(model=None, max_steps=3, max_chars=2000):
        settings = load_settings({
            "MODEL_PROVIDER": "fake",
            "AGENT_MAX_STEPS": str(max_steps),
            "MAX_QUESTION_CHARS": str(max_chars),
            "EMPLOYEES_PATH": str(employees_path),
            "API_KEYS": API_KEYS_ENV,
            "RATE_LIMIT_PER_MINUTE": "1000",
        })
        chosen = model or FakeModel(directory.departments())
        app = create_app(settings=settings, model=chosen, directory=directory)
        return TestClient(app, headers=AUTH_HEADERS)

    return build


@pytest.fixture(name="make_secure_client")
def make_secure_client_fixture(employees_path, directory):
    """Fábrica de ``(client, stream, clock)`` SIN cabecera de clave por defecto.

    :param employees_path: Archivo temporal de empleados.
    :type employees_path: pathlib.Path
    :param directory: Directorio de empleados.
    :type directory: app.directory.EmployeeDirectory
    :return: Función que construye el cliente, el flujo y el reloj.
    :rtype: collections.abc.Callable

    Interfaces de la sesión 4 (el desarrollador debe respetarlas):

    - ``Settings`` adds ``environment``, ``api_keys`` (dict ``client -> key``,
      hidden from ``repr``) and ``rate_limit_per_minute``.
    - ``app.security.parse_api_keys(raw) -> dict``,
      ``authenticate(api_keys, received) -> str | None`` and
      ``RateLimiter(limit, clock)`` with ``check(client) -> int | None``:
      ``None`` when the request passes, otherwise the seconds to wait.
    - ``app.compliance.check_production(settings) -> list[str]``.
    - ``app.observability.client_var`` (a ``ContextVar``, default ``None``).
    - ``create_app(..., limiter=None)``.
    """

    def build(env=None, clock=None):
        values = {
            "MODEL_PROVIDER": "fake",
            "EMPLOYEES_PATH": str(employees_path),
            "API_KEYS": API_KEYS_ENV,
            "RATE_LIMIT_PER_MINUTE": "1000",
        }
        values.update(env or {})
        settings = load_settings(values)
        clock = clock or FakeClock()
        stream = io.StringIO()
        logger = JsonLogger(
            settings.service_name, clock, stream, masking=settings.pii_masking
        )
        app = create_app(
            settings=settings, model=FakeModel(directory.departments()),
            directory=directory, clock=clock, logger=logger,
        )
        client = TestClient(app, raise_server_exceptions=False)
        return client, stream, clock

    return build
