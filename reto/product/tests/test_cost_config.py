"""Pruebas de la configuracion nueva de costos y del gateway."""

from pathlib import Path

import pytest

from conftest import CF_TOKEN, GATEWAY_ENV, LARGE_MODEL, SMALL_MODEL
from app.config import ConfigError, load_settings


def test_cost_settings_have_the_documented_defaults():
    settings = load_settings({})

    assert settings.cf_gateway_id == "default"
    assert (settings.model_small, settings.model_large) == (SMALL_MODEL, LARGE_MODEL)
    assert settings.routing is True
    assert settings.router_max_chars == 80
    assert settings.history_window == 6
    assert settings.model_max_tokens == 300
    assert settings.model_temperature == 0
    assert settings.cache_ttl_seconds == 0
    assert Path(settings.prices_path).parts[-2:] == ("data", "model_prices.json")


@pytest.mark.parametrize(
    "variable", ["CF_ACCOUNT_ID", "CF_GATEWAY_ID", "CF_API_TOKEN"]
)
def test_gateway_needs_every_cloudflare_variable_and_hides_the_token(
    make_settings, variable
):
    valid = make_settings(**GATEWAY_ENV)

    with pytest.raises(ConfigError) as error:
        make_settings(**{**GATEWAY_ENV, variable: ""})

    assert variable in str(error.value)
    assert CF_TOKEN not in str(error.value)
    assert CF_TOKEN not in repr(valid)


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("ROUTING", "maybe"),
        ("ROUTER_MAX_CHARS", "0"),
        ("HISTORY_WINDOW", "-1"),
        ("MODEL_MAX_TOKENS", "0"),
        ("MODEL_TEMPERATURE", "3"),
        ("MODEL_TEMPERATURE", "cold"),
        ("CACHE_TTL_SECONDS", "-5"),
        ("MODEL_SMALL", "@cf/without/price"),
        ("PRICES_PATH", "missing/prices.json"),
    ],
)
def test_invalid_cost_value_prevents_startup(make_settings, variable, value):
    with pytest.raises(ConfigError) as error:
        make_settings(**{variable: value})

    assert variable in str(error.value)
