"""Pruebas unitarias de la configuración (``app.config``)."""

from pathlib import Path

import pytest

from conftest import GATEWAY_ENV, LARGE_MODEL, SMALL_MODEL

from app.config import ConfigError, load_config


def test_defaults_are_used_when_environment_is_empty():
    config = load_config({})

    assert config.model_provider == "fake"
    assert config.agent_max_steps == 3
    assert config.max_question_chars == 2000
    assert Path(config.employees_path).as_posix().endswith("data/employees.json")


@pytest.mark.parametrize("value", ["0", "abc"])
def test_invalid_max_steps_stops_startup_with_clear_message(value):
    with pytest.raises(ConfigError, match="AGENT_MAX_STEPS"):
        load_config({"AGENT_MAX_STEPS": value})


def test_invalid_max_question_chars_stops_startup():
    with pytest.raises(ConfigError, match="MAX_QUESTION_CHARS"):
        load_config({"MAX_QUESTION_CHARS": "-5"})


def test_unknown_model_provider_stops_startup():
    with pytest.raises(ConfigError, match="MODEL_PROVIDER"):
        load_config({"MODEL_PROVIDER": "openai"})


def test_cost_lever_defaults_are_used_when_environment_is_empty():
    config = load_config({})

    assert config.model_small == SMALL_MODEL
    assert config.model_large == LARGE_MODEL
    assert config.routing is True
    assert config.router_max_chars == 80
    assert config.history_window == 6
    assert config.model_max_tokens == 300
    assert config.model_temperature == 0
    assert config.cache_ttl_seconds == 0
    assert config.cf_gateway_id == "default"
    assert Path(config.prices_path).as_posix().endswith("data/model_prices.json")


@pytest.mark.parametrize(
    "name, value",
    [
        ("ROUTING", "maybe"),
        ("MODEL_TEMPERATURE", "3"),
        ("CACHE_TTL_SECONDS", "-1"),
    ],
)
def test_invalid_cost_setting_stops_startup(name, value):
    with pytest.raises(ConfigError, match=name):
        load_config({name: value})


def test_gateway_without_api_token_stops_startup():
    environ = {**GATEWAY_ENV, "CF_API_TOKEN": ""}

    with pytest.raises(ConfigError, match="CF_API_TOKEN"):
        load_config(environ)


def test_gateway_without_account_id_stops_startup():
    environ = {**GATEWAY_ENV, "CF_ACCOUNT_ID": ""}

    with pytest.raises(ConfigError, match="CF_ACCOUNT_ID"):
        load_config(environ)


@pytest.mark.parametrize(
    "name, value",
    [
        ("ROUTER_MAX_CHARS", "abc"),
        ("HISTORY_WINDOW", "-1"),
        ("MODEL_MAX_TOKENS", "0"),
    ],
)
def test_invalid_router_window_or_output_cap_stops_startup(name, value):
    with pytest.raises(ConfigError, match=name):
        load_config({name: value})


def test_env_example_lists_every_cost_setting_without_secrets():
    env_example = Path(__file__).resolve().parent.parent / ".env.example"
    settings = {}
    for line in env_example.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            name, _, value = line.partition("=")
            settings[name.strip()] = value.strip()

    expected = {
        "MODEL_PROVIDER", "CF_ACCOUNT_ID", "CF_GATEWAY_ID", "CF_API_TOKEN",
        "MODEL_SMALL", "MODEL_LARGE", "ROUTING", "ROUTER_MAX_CHARS",
        "HISTORY_WINDOW", "MODEL_MAX_TOKENS", "MODEL_TEMPERATURE",
        "CACHE_TTL_SECONDS", "PRICES_PATH", "LANGSMITH_TRACING",
        "LANGSMITH_API_KEY", "HIDE_INPUTS", "HIDE_OUTPUTS",
    }
    assert expected <= set(settings)
    assert settings["CF_API_TOKEN"] == ""
    assert settings["LANGSMITH_API_KEY"] == ""


def test_api_token_never_appears_in_the_config_repr():
    config = load_config(GATEWAY_ENV)

    assert config.cf_api_token == GATEWAY_ENV["CF_API_TOKEN"]
    assert GATEWAY_ENV["CF_API_TOKEN"] not in repr(config)


def test_tracing_is_off_and_hides_text_by_default():
    config = load_config({})

    assert config.langsmith_tracing is False
    assert config.hide_inputs is True
    assert config.hide_outputs is True
    assert config.langsmith_api_key == ""


@pytest.mark.parametrize("name", ["LANGSMITH_TRACING", "HIDE_INPUTS", "HIDE_OUTPUTS"])
def test_invalid_tracing_setting_stops_startup(name):
    with pytest.raises(ConfigError, match=name):
        load_config({name: "maybe"})


def test_langsmith_api_key_never_appears_in_the_config_repr():
    secret = "langsmith-key-that-must-stay-secret"

    config = load_config({"LANGSMITH_TRACING": "true", "LANGSMITH_API_KEY": secret})

    assert config.langsmith_tracing is True
    assert config.langsmith_api_key == secret
    assert secret not in repr(config)


def test_production_settings_have_safe_defaults():
    config = load_config({})

    assert config.environment == "development"
    assert config.api_keys == {}
    assert config.rate_limit_per_minute == 30


@pytest.mark.parametrize(
    ("name", "value"),
    [("ENVIRONMENT", "staging"), ("RATE_LIMIT_PER_MINUTE", "0")],
)
def test_invalid_environment_or_rate_limit_stops_startup(name, value):
    with pytest.raises(ConfigError, match=name):
        load_config({name: value})


def test_api_keys_never_appear_in_the_config_repr():
    secret = "acme-key-that-must-stay-secret"

    config = load_config({"API_KEYS": f"acme:{secret}"})

    assert config.api_keys == {"acme": secret}
    assert secret not in repr(config)
