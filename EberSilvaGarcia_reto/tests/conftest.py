"""Fixtures compartidas: reloj fijo, configuración y aplicación con modelo simulado."""

import asyncio
import io
import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.clock import FixedClock
from app.config import load_settings
from app.llm.base import Completion
from app.main import create_app
from app.observability.logs import JsonLogger
from app.service import HrService, build_services

KEY = "test-key-0123456789"
METRICS_ONLY_KEY = "metrics-key-0123456789"
NOW = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)


def run(coro):
    """Corre una corutina en las pruebas síncronas."""
    return asyncio.run(coro)


def make_env(**extra):
    """Variables de entorno de prueba con dos clientes."""
    env = {
        "API_KEYS": f"portal:{KEY},grafana:{METRICS_ONLY_KEY}",
        "CLIENT_SCOPES": "grafana:metrics",
        "RATE_LIMIT_PER_MINUTE": "1000",
    }
    env.update(extra)
    return env


class ScriptedModel:
    """Modelo que responde un guion fijo (para probar casos raros)."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    async def complete(self, messages, model, max_tokens):
        del max_tokens
        self.calls.append(messages)
        text = self.replies.pop(0) if self.replies else '{"answer": "fin"}'
        if isinstance(text, Exception):
            raise text
        if isinstance(text, dict):
            text = json.dumps(text, ensure_ascii=False)
        return Completion(text, 10, 5, model)


@pytest.fixture
def clock():
    return FixedClock(NOW)


@pytest.fixture
def log_stream():
    return io.StringIO()


@pytest.fixture
def make_service(clock, log_stream):
    def factory(model=None, **env):
        settings = load_settings(make_env(**env))
        logger = JsonLogger("test", clock, log_stream)
        return HrService(build_services(settings, clock, logger, model=model))

    return factory


@pytest.fixture
def make_client(clock, log_stream):
    def factory(model=None, **env):
        settings = load_settings(make_env(**env))
        logger = JsonLogger("test", clock, log_stream)
        app = create_app(settings, clock, model=model, logger=logger)
        client = TestClient(app)
        client.headers["X-API-Key"] = KEY
        return client

    return factory


@pytest.fixture
def client(make_client):
    with make_client() as test_client:
        yield test_client


def log_events(stream):
    """Eventos JSON escritos en el log."""
    return [json.loads(line) for line in stream.getvalue().splitlines() if line]
