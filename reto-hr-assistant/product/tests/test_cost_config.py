"""Pruebas de la configuración nueva: gateway y palancas de costo."""

import pytest

from app.config import ConfigError, load_settings

FAKE_TOKEN = "secret-token-xyz"


@pytest.mark.parametrize("missing", ["CF_ACCOUNT_ID", "CF_API_TOKEN"])
def test_gateway_without_cloudflare_credentials_does_not_start(
    gateway_environ, missing
):
    del gateway_environ[missing]

    with pytest.raises(ConfigError, match=missing) as error:
        load_settings(gateway_environ)

    assert FAKE_TOKEN not in str(error.value)


@pytest.mark.parametrize(
    ("name", "value"), [("HISTORY_WINDOW", "-1"), ("MODEL_TEMPERATURE", "hot")]
)
def test_invalid_cost_setting_does_not_start(name, value):
    with pytest.raises(ConfigError, match=name):
        load_settings({name: value})
