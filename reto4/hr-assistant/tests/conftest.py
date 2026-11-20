"""Piezas compartidas por las pruebas del HR Assistant.

Contrato que las pruebas esperan del código de ``product/app``:

- ``app.config.load_config(environ)`` devuelve una configuración con
  ``model_provider``, ``agent_max_steps``, ``max_question_chars``,
  ``employees_path`` y, desde la sesión 3, ``cf_account_id``,
  ``cf_gateway_id``, ``cf_api_token``, ``model_small``, ``model_large``,
  ``routing``, ``router_max_chars``, ``history_window``, ``model_max_tokens``,
  ``model_temperature``, ``cache_ttl_seconds`` y ``prices_path``; un valor
  inválido lanza ``app.config.ConfigError``.
- ``app.directory.load_directory(path)`` devuelve un directorio con
  ``get_employee(employee_id)``, ``search_by_department(department)`` y
  ``departments()``.
- ``app.llm.ModelReply(text, input_tokens, output_tokens, model, cached)``,
  ``app.llm.FakeModel(name, departments)``,
  ``app.llm.GatewayModel(name, config, http_client)``,
  ``app.llm.ModelUnavailableError`` y
  ``app.llm.build_models(config, directory)``, que devuelve
  ``{config.model_small: ..., config.model_large: ...}``.
- ``app.router.choose_model(question, config)`` devuelve
  ``(model_name, route)``.
- ``app.pricing.load_prices(path)`` devuelve una tabla con
  ``cost(model, input_tokens, output_tokens)`` en USD; un archivo inválido
  lanza ``ConfigError``.
- ``app.agent.Agent(model, directory, max_steps, prices=None,
  history_window=None).run(question, history)`` devuelve un resultado con
  ``answer``, ``steps``, ``tools_used``, ``input_tokens``, ``output_tokens``,
  ``model``, ``cached_calls`` y ``cost_usd``. El costo de cada llamada se
  calcula con ``reply.model``; una llamada con ``reply.cached`` cuesta 0.
- ``app.main.create_app(config, models, directory, prices,
  observability=None, rate_limiter=None)`` devuelve la app FastAPI; lanza
  ``ConfigError`` si ``MODEL_SMALL`` o ``MODEL_LARGE`` no tienen precio. Sin
  ``rate_limiter`` arma uno con el reloj de ``observability``.

Contrato nuevo de la sesión 4 (spec/04-production.md, ADR 0009 a 0011):

- La configuración agrega ``environment`` (``development`` o
  ``production``), ``api_keys`` (dict cliente a clave, fuera de ``repr``) y
  ``rate_limit_per_minute`` (por omisión 30). Con ``ENVIRONMENT=production``
  ``load_config`` lanza un solo ``ConfigError`` con todas las reglas
  incumplidas.
- ``app.auth.parse_api_keys(raw)`` devuelve el dict cliente a clave y
  ``app.auth.KeyRing(api_keys).client_for(key)`` devuelve el cliente o
  ``None``.
- ``app.ratelimit.RateLimiter(limit_per_minute, clock).check(client)``
  devuelve ``None`` o los segundos de ``Retry-After``.
- ``app.compliance.check_production(config)`` devuelve la lista de reglas
  incumplidas.
- ``Agent(..., client=...)`` y ``tracer.wrap(..., client=...)`` llevan el
  cliente a los metadatos de la traza.

Para no romper las pruebas de las sesiones 1 a 3, ``build_client`` define
siempre un cliente de prueba con clave y un límite alto, y manda la clave en
``X-API-Key`` salvo que se pida lo contrario.

"""

import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

PRODUCT_ROOT = Path(__file__).resolve().parent.parent
if str(PRODUCT_ROOT) not in sys.path:
    sys.path.insert(0, str(PRODUCT_ROOT))

# Las importaciones de ``app`` van después de agregar ``product/`` a sys.path,
# para que pytest las encuentre aunque se corra desde otra carpeta.
# pylint: disable=wrong-import-position
from app.config import load_config
from app.directory import load_directory
from app.llm import GatewayModel, ModelReply, build_models
from app.main import create_app
from app.observability import build_observability
from app.pricing import load_prices

# pylint: enable=wrong-import-position

DATA_PATH = PRODUCT_ROOT / "data" / "employees.json"
PRICES_PATH = PRODUCT_ROOT / "data" / "model_prices.json"
CAP_MESSAGE = "No pude completar la respuesta. Intenta con una pregunta más concreta."
SMALL_MODEL = "@cf/meta/llama-3.1-8b-instruct-fast"
LARGE_MODEL = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
GATEWAY_ENV = {
    "MODEL_PROVIDER": "gateway",
    "CF_ACCOUNT_ID": "account-123",
    "CF_GATEWAY_ID": "gateway-hr",
    "CF_API_TOKEN": "token-that-must-stay-secret",
}
GATEWAY_URL = (
    "https://gateway.ai.cloudflare.com/v1/account-123/gateway-hr"
    "/workers-ai/v1/chat/completions"
)
API_KEY_HEADER = "X-API-Key"
TEST_CLIENT = "tests"
TEST_API_KEY = "tests-key-0123456789abcdef"
BASE_TEST_ENV = {
    "API_KEYS": f"{TEST_CLIENT}:{TEST_API_KEY}",
    "RATE_LIMIT_PER_MINUTE": "1000",
}
PRODUCTION_KEY = "acme-production-key-0001"
PRODUCTION_ENV = {
    **GATEWAY_ENV,
    "ENVIRONMENT": "production",
    "API_KEYS": f"acme:{PRODUCTION_KEY}",
    "LANGSMITH_TRACING": "true",
    "HIDE_INPUTS": "true",
    "HIDE_OUTPUTS": "true",
}
FIXED_NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


class FakeClock:
    """Reloj de prueba que solo avanza cuando la prueba lo pide.

    :param start: Segundos iniciales del contador monótono
    :type start: float
    """

    def __init__(self, start=0.0):
        self.seconds = start

    def now(self):
        """Devuelve una hora fija en UTC.

        :return: Hora fija
        :rtype: datetime.datetime
        """
        return FIXED_NOW

    def monotonic(self):
        """Devuelve los segundos acumulados.

        :return: Contador monótono
        :rtype: float
        """
        return self.seconds

    def advance(self, seconds):
        """Avanza el reloj sin dormir.

        :param seconds: Segundos que avanza
        :type seconds: float
        """
        self.seconds += seconds


class ScriptedModel:
    """Modelo de prueba que devuelve respuestas fijas, en orden.

    :param replies: Tuplas ``(texto, tokens_entrada, tokens_salida)`` o
        ``(texto, tokens_entrada, tokens_salida, cacheada)``
    :type replies: list[tuple]
    :param name: Nombre del modelo con el que se calcula el precio
    :type name: str
    """

    def __init__(self, replies, name="fake"):
        self._replies = list(replies)
        self.name = name
        self.calls = []

    def complete(self, messages):
        """Guarda los mensajes recibidos y devuelve la siguiente respuesta.

        :param messages: Conversación enviada por el agente
        :type messages: list[dict]
        :return: La respuesta programada
        :rtype: app.llm.ModelReply
        """
        self.calls.append(copy.deepcopy(messages))
        text, input_tokens, output_tokens, *rest = self._replies.pop(0)
        return ModelReply(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=self.name,
            cached=bool(rest and rest[0]),
        )


class AlwaysToolModel:
    """Modelo de prueba que siempre pide una herramienta y nunca responde."""

    def complete(self, _messages):
        """Pide ``get_employee`` sin importar la conversación.

        :param _messages: Conversación enviada por el agente; no se usa
        :type _messages: list[dict]
        :return: Una petición de herramienta
        :rtype: app.llm.ModelReply
        """
        request = {"tool": "get_employee", "args": {"employee_id": "EMP-0004"}}
        return ModelReply(
            text=json.dumps(request),
            input_tokens=1,
            output_tokens=1,
            model="fake",
            cached=False,
        )


def gateway_response(content, prompt_tokens, completion_tokens, headers=None):
    """Arma la respuesta HTTP que devolvería el AI Gateway.

    :param content: Texto que devuelve el modelo
    :type content: str
    :param prompt_tokens: Valor de ``usage.prompt_tokens``
    :type prompt_tokens: int
    :param completion_tokens: Valor de ``usage.completion_tokens``
    :type completion_tokens: int
    :param headers: Encabezados extra, por ejemplo ``cf-aig-cache-status``
    :type headers: dict or None
    :return: Respuesta simulada
    :rtype: httpx.Response
    """
    body = {
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        },
    }
    return httpx.Response(200, json=body, headers=headers or {})


def gateway_http_client(handler):
    """Cliente ``httpx`` que responde con ``handler`` y nunca toca la red.

    :param handler: Función ``(request) -> httpx.Response``
    :type handler: callable
    :return: Cliente con transporte simulado
    :rtype: httpx.Client
    """
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def directory():
    """Directorio real cargado desde ``product/data/employees.json``."""
    return load_directory(DATA_PATH)


@pytest.fixture
def prices():
    """Tabla de precios real cargada desde ``product/data/model_prices.json``."""
    return load_prices(PRICES_PATH)


@pytest.fixture
def build_client():
    """Fábrica de clientes HTTP con dependencias inyectadas.

    :return: Función ``(environ, model, models, api_key, clock) ->
        TestClient``. Si se da ``model``, ese modelo atiende con los dos
        nombres; si se da ``models``, se usa ese diccionario; si no, los
        modelos que indica la configuración. ``environ`` se mezcla sobre
        ``BASE_TEST_ENV``. ``api_key`` se manda en ``X-API-Key`` (``None``: sin
        clave). ``clock`` reemplaza el reloj de la observabilidad
    :rtype: callable
    """

    def _build(  # pylint: disable=too-many-arguments
        environ=None, model=None, models=None, *, api_key=TEST_API_KEY,
        clock=None,
    ):
        config = load_config({**BASE_TEST_ENV, **(environ or {})})
        employees = load_directory(DATA_PATH)
        if models is None and model is not None:
            models = {config.model_small: model, config.model_large: model}
        if models is None:
            models = build_models(config, employees)
        observability = None
        if clock is not None:
            observability = build_observability(config, clock=clock)
        app = create_app(
            config=config,
            models=models,
            directory=employees,
            prices=load_prices(PRICES_PATH),
            observability=observability,
        )
        headers = {API_KEY_HEADER: api_key} if api_key else {}
        return TestClient(app, headers=headers)

    return _build


@pytest.fixture
def build_gateway_client(build_client):
    """Fábrica de clientes HTTP con el modelo real y un gateway simulado.

    :return: Función ``(handler, extra_environ) -> TestClient``
    :rtype: callable
    """

    def _build(handler, extra_environ=None):
        environ = {**GATEWAY_ENV, **(extra_environ or {})}
        config = load_config(environ)
        http_client = gateway_http_client(handler)
        models = {
            name: GatewayModel(name, config, http_client)
            for name in (config.model_small, config.model_large)
        }
        return build_client(environ, models=models)

    return _build
