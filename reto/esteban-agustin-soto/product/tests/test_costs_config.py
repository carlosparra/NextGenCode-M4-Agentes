"""Unit tests for the session 3 configuration."""

import pytest

from app.config import load_settings

CF_VARIABLES = ["CF_ACCOUNT_ID", "CF_GATEWAY_ID", "CF_API_TOKEN"]
GATEWAY_ENV = {"MODEL_PROVIDER": "gateway", "CF_ACCOUNT_ID": "acct",
               "CF_GATEWAY_ID": "gw", "CF_API_TOKEN": "s3cret-token-value"}


def test_cost_settings_have_the_documented_defaults():
    settings = load_settings({"MODEL_PROVIDER": "fake"})
    assert settings.model_small == "@cf/meta/llama-3.1-8b-instruct-fast"
    assert settings.model_large == "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    assert settings.routing is True
    assert settings.router_max_chars == 80
    assert settings.history_window == 6
    assert settings.model_max_tokens == 300
    assert settings.model_temperature == 0
    assert settings.cache_ttl_seconds == 0
    assert settings.cf_gateway_id == "default"


def test_cost_settings_can_be_overridden():
    settings = load_settings({
        "MODEL_PROVIDER": "fake", "ROUTING": "false", "HISTORY_WINDOW": "2",
        "CACHE_TTL_SECONDS": "60", "MODEL_MAX_TOKENS": "50",
    })
    assert settings.routing is False
    assert settings.history_window == 2
    assert settings.cache_ttl_seconds == 60
    assert settings.model_max_tokens == 50


def test_invalid_cost_values_are_rejected():
    bad_values = [("ROUTING", "maybe"), ("ROUTER_MAX_CHARS", "abc"),
                  ("HISTORY_WINDOW", "0"), ("MODEL_MAX_TOKENS", "x"),
                  ("CACHE_TTL_SECONDS", "-1")]
    for name, value in bad_values:
        with pytest.raises(ValueError, match=name):
            load_settings({"MODEL_PROVIDER": "fake", name: value})


def test_gateway_needs_every_cloudflare_variable():
    assert load_settings(GATEWAY_ENV).model_provider == "gateway"
    for name in CF_VARIABLES:
        env = {k: v for k, v in GATEWAY_ENV.items() if k != name}
        if name == "CF_GATEWAY_ID":
            assert load_settings(env).cf_gateway_id == "default"
            continue
        with pytest.raises(ValueError, match=name):
            load_settings(env)


def test_settings_repr_hides_the_token():
    settings = load_settings(GATEWAY_ENV)
    assert "s3cret-token-value" not in repr(settings)
