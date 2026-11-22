"""Pruebas unitarias del registro de claves, del límite por minuto y de las trazas."""

import sys
import types
from contextlib import contextmanager

from app.config import Secret, load_settings
from app.security import ApiKeyRegistry, RateLimiter
from app.tracing import Tracer


def test_registry_finds_the_client_only_for_its_exact_key():
    registry = ApiKeyRegistry(
        {"alice": Secret("key-alice-123"), "bob": Secret("key-bob-456")}
    )

    assert registry.client_for("key-alice-123") == "alice"
    assert registry.client_for("key-bob-456") == "bob"
    for wrong in ("key-bob-45", "KEY-BOB-456", "key-bob-456 ", "", None):
        assert registry.client_for(wrong) is None


def test_rate_limiter_allows_the_exact_limit_and_blocks_one_more():
    limiter = RateLimiter(limit_per_minute=3)

    decisions = [limiter.allow("alice", 10.0) for _ in range(4)]

    assert decisions == [True, True, True, False]
    assert limiter.allow("bob", 10.0) is True


def test_rate_limiter_window_slides_and_retry_after_is_rounded_up_never_zero():
    limiter = RateLimiter(limit_per_minute=1)

    assert limiter.allow("alice", 100.0) is True
    assert limiter.allow("alice", 100.5) is False
    # Faltan 59.5 s: se redondea hacia arriba.
    assert limiter.retry_after("alice", 100.5) == 60
    assert limiter.allow("alice", 159.9) is False
    # Faltan 0.1 s: nunca se responde 0.
    assert limiter.retry_after("alice", 159.9) == 1
    # Los rechazos no ocupan cupo: pasado el minuto de la primera, vuelve a pasar.
    assert limiter.allow("alice", 160.5) is True


def test_trace_metadata_names_the_client(monkeypatch):
    seen = {}

    @contextmanager
    def tracing_context(**kwargs):
        seen.update(kwargs)
        yield

    fake_langsmith = types.ModuleType("langsmith")
    fake_langsmith.Client = lambda **kwargs: None
    fake_langsmith.traceable = lambda **kwargs: (lambda function: function)
    fake_langsmith.tracing_context = tracing_context
    monkeypatch.setitem(sys.modules, "langsmith", fake_langsmith)
    settings = load_settings(
        {"LANGSMITH_TRACING": "true", "LANGSMITH_API_KEY": "test-key"}
    )

    with Tracer(settings).request_scope("req-9", "alice"):
        pass

    assert seen["metadata"] == {"request_id": "req-9", "client": "alice"}
