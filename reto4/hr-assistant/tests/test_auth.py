"""Pruebas unitarias de las claves por cliente (``app.auth``, ADR 0009)."""

import pytest

from app.auth import KeyRing, parse_api_keys
from app.config import ConfigError, load_config


def test_api_keys_are_parsed_into_clients():
    assert parse_api_keys("acme:key-one-123,globex:key-two-456") == {
        "acme": "key-one-123",
        "globex": "key-two-456",
    }
    assert parse_api_keys("") == {}


@pytest.mark.parametrize(
    ("raw", "position", "entry", "secret"),
    [
        ("acme:first-key-123,globexsecretvalue", 2, "globexsecretvalue",
         "globexsecretvalue"),
        (":lonely-secret-key", 1, ":lonely-secret-key", "lonely-secret-key"),
        ("acme:", 1, "acme:", None),
        ("acme:first-key-123,", 2, "", None),
        ("acme:first-key-123,acme:other-key-4567", 2, "acme:other-key-4567",
         "other-key-4567"),
        ("acme:shared-key-999,globex:shared-key-999", 2,
         "globex:shared-key-999", "shared-key-999"),
    ],
    ids=[
        "missing_colon", "empty_client", "empty_key", "trailing_comma",
        "repeated_client", "repeated_key",
    ],
)
def test_malformed_api_keys_stop_startup_without_revealing_the_value(
    raw, position, entry, secret
):
    with pytest.raises(ConfigError) as error:
        load_config({"API_KEYS": raw})

    message = str(error.value)
    assert "API_KEYS" in message
    assert str(position) in message
    assert str(len(entry)) in message
    if secret is not None:
        assert secret not in message


def test_key_ring_finds_the_client_only_for_an_exact_key():
    ring = KeyRing(
        {"acme": "acme-key-0123456789", "globex": "globex-key-0123456789"}
    )

    assert ring.client_for("globex-key-0123456789") == "globex"
    assert ring.client_for("acme-key-012345678") is None
    assert ring.client_for("") is None
    assert KeyRing({}).client_for("acme-key-0123456789") is None
