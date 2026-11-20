"""Pruebas de la API documentada y sana y de la configuracion nueva (reto)."""

import os

import pytest
from fastapi.testclient import TestClient

from conftest import TEST_API_KEY, build_default_app
from app.config import ConfigError

APP_VERSION = "2.3.4"
ASK_ERRORS = {"400", "401", "422", "429", "502"}


@pytest.fixture
def public_client(make_settings, directory, clock, log_stream):
    """Cliente sin clave contra la app con ``APP_VERSION`` fijada."""
    env = {"APP_VERSION": APP_VERSION}
    app = build_default_app(make_settings, directory, clock, log_stream, env=env)
    return TestClient(app)


def test_openapi_documents_version_tags_errors_and_the_key_scheme(public_client):
    response = public_client.get("/openapi.json")

    assert response.status_code == 200
    spec = response.json()
    assert spec["info"]["title"] == "HR Assistant API"
    assert spec["info"]["version"] == APP_VERSION
    assert spec["info"].get("description")
    assert {"chat", "operations"} <= {tag["name"] for tag in spec.get("tags", [])}
    ask = spec["paths"]["/ask"]["post"]
    assert ASK_ERRORS <= set(ask["responses"])
    for path, method in (("/ask", "post"), ("/health", "get"), ("/metrics", "get")):
        assert spec["paths"][path][method].get("summary"), path
    schemes = spec["components"]["securitySchemes"].values()
    assert {"type": "apiKey", "in": "header", "name": "X-API-Key"} in [
        {key: scheme.get(key) for key in ("type", "in", "name")} for scheme in schemes
    ]
    assert TEST_API_KEY not in response.text
    docs = public_client.get("/docs")
    assert docs.status_code == 200
    assert TEST_API_KEY not in docs.text


def test_health_reports_status_pid_and_version(public_client):
    response = public_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "pid": os.getpid(),
        "version": APP_VERSION,
    }


def test_new_settings_have_defaults_and_reject_invalid_values(make_settings):
    settings = make_settings()

    assert settings.app_version == "1.0.0"
    assert settings.response_cache_ttl_seconds == 0
    assert settings.response_cache_size == 256
    assert settings.pii_policy == "mask"
    assert settings.max_answer_chars == 2000
    invalid = {
        "PII_POLICY": "allow",
        "RESPONSE_CACHE_SIZE": "0",
        "RESPONSE_CACHE_TTL_SECONDS": "-1",
        "MAX_ANSWER_CHARS": "zero",
    }
    for name, value in invalid.items():
        with pytest.raises(ConfigError, match=name):
            make_settings(**{name: value})
