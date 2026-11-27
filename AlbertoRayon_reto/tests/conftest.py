"""Piezas compartidas por las pruebas: configuración, reloj y cliente HTTP."""

from contextlib import ExitStack
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.clock import FixedClock
from app.config import load_settings
from app.main import create_app

KEY = "unit-test-key-0123456789"
HEADERS = {"X-API-Key": KEY}
TODAY = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)


def make_settings(**env):
    """Configuración de pruebas: modelo simulado y una clave con todos los permisos."""
    base = {"API_KEYS": f"tester:{KEY}", "RATE_LIMIT_PER_MINUTE": "1000"}
    return load_settings({**base, **{name: str(value) for name, value in env.items()}})


class ScriptedModel:
    """Modelo que responde lo que la prueba le dicta, en orden."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def complete(self, messages, model):
        # Import local: evita que conftest dependa del orden de carga de app.llm
        from app.llm import Completion  # pylint: disable=import-outside-toplevel

        self.calls.append((messages, model))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return Completion(reply, 10, 5, model)


@pytest.fixture
def clock():
    return FixedClock(TODAY)


@pytest.fixture
def make_client(clock):
    """Fábrica de clientes HTTP sobre la aplicación, con dependencias inyectadas."""
    def build(model=None, **env):
        app = create_app(make_settings(**env), model=model, clock=clock)
        client = stack.enter_context(
            TestClient(app, base_url="http://localhost", headers=HEADERS)
        )
        return client

    with ExitStack() as stack:
        yield build


@pytest.fixture
def client(make_client):
    return make_client()
