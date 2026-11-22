"""Pasos de ``features/compliance.feature``: reglas de producción al arrancar."""

import io
import secrets
import sys
import types
from contextlib import nullcontext

import pytest
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, scenarios, then, when

from app.config import ConfigError, load_settings
from app.main import create_app

scenarios("features/compliance.feature")

PRODUCTION_KEY = secrets.token_urlsafe(24)
SHORT_KEY = "short-key"
EMPTY_MARKER = "(empty)"


def _fake_langsmith():
    """Arma un módulo ``langsmith`` falso para que nada salga a la red.

    :return: Módulo con ``Client``, ``traceable`` y ``tracing_context``
    :rtype: types.ModuleType
    """
    module = types.ModuleType("langsmith")
    module.Client = lambda **kwargs: None
    module.traceable = lambda **kwargs: (lambda function: function)
    module.tracing_context = lambda **kwargs: nullcontext()
    return module


@pytest.fixture
def environ():
    """Variables de entorno del escenario.

    :return: Diccionario que llenan los pasos
    :rtype: dict
    """
    return {}


@given("a production configuration that is otherwise safe")
def safe_production(environ, gateway_environ, monkeypatch):
    """Producción con gateway, clave larga y trazas que ocultan textos."""
    monkeypatch.setitem(sys.modules, "langsmith", _fake_langsmith())
    environ.update(gateway_environ)
    environ.update(
        {
            "ENVIRONMENT": "production",
            "API_KEYS": f"ops:{PRODUCTION_KEY}",
            "LANGSMITH_TRACING": "true",
            "LANGSMITH_API_KEY": "lsv2-fake-key",
            "HIDE_INPUTS": "true",
            "HIDE_OUTPUTS": "true",
        }
    )


@given(parsers.parse('the variable "{name}" is set to "{value}"'))
def set_variable(environ, name, value):
    """Cambia una variable; ``(empty)`` la deja vacía."""
    environ[name] = "" if value == EMPTY_MARKER else value


@when("the assistant starts", target_fixture="startup")
def assistant_starts(environ):
    """Lee la configuración y arma la app, guardando el error si lo hay."""
    try:
        app = create_app(settings=load_settings(environ), log_stream=io.StringIO())
    except ConfigError as error:
        return {"app": None, "error": error}
    return {"app": app, "error": None}


@then(parsers.parse('it refuses to start with an error that mentions "{name}"'))
def refuses_to_start(startup, name):
    """La app no se creó y el error nombra la variable culpable."""
    assert startup["app"] is None
    assert name in str(startup["error"])


@then("the error does not reveal any API key")
def error_hides_keys(startup, gateway_environ):
    """El mensaje no trae ninguna clave ni el token del gateway."""
    message = str(startup["error"])
    assert PRODUCTION_KEY not in message
    assert SHORT_KEY not in message
    assert gateway_environ["CF_API_TOKEN"] not in message


@then("it starts and answers the health check")
def starts_and_is_healthy(startup):
    """La app se creó y ``/health`` responde ``200``."""
    assert startup["error"] is None
    assert TestClient(startup["app"]).get("/health").status_code == 200
