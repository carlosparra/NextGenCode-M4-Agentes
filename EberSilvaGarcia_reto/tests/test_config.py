"""Configuración y compliance como código."""

import pytest

from app.config import ConfigError, load_settings, parse_api_keys, parse_scopes

STRONG = "k" * 20


def test_defaults_are_safe():
    settings = load_settings({})
    assert settings.model_provider == "fake"
    assert settings.hide_inputs and settings.hide_outputs
    assert settings.answer_cache_ttl_seconds == 0
    assert not settings.is_production


@pytest.mark.parametrize(
    "name,value",
    [
        ("AGENT_MAX_STEPS", "0"),
        ("AGENT_MAX_STEPS", "x"),
        ("MODEL_TEMPERATURE", "-1"),
        ("MODEL_TEMPERATURE", "hot"),
        ("ROUTING", "maybe"),
        ("MODEL_PROVIDER", "openai"),
    ],
)
def test_invalid_values_stop_the_start(name, value):
    with pytest.raises(ConfigError, match=name):
        load_settings({name: value})


def test_relative_paths_are_resolved_from_the_project():
    settings = load_settings({"EMPLOYEES_PATH": "data/employees.json"})
    assert settings.employees_path.is_absolute()


def test_api_keys_with_scopes():
    clients = parse_api_keys("a:one,b:two", "b:metrics|ask")
    assert clients[0].scopes == frozenset({"ask", "metrics", "mcp"})
    assert clients[1].scopes == frozenset({"metrics", "ask"})
    assert "one" not in repr(clients[0])


def test_broken_api_keys_never_show_the_value():
    with pytest.raises(ConfigError) as error:
        parse_api_keys("secret-without-client")
    assert "secret-without-client" not in str(error.value)
    assert "entrada 1" in str(error.value)


def test_repeated_clients_are_rejected():
    with pytest.raises(ConfigError, match="repite"):
        parse_api_keys("a:one,a:two")


def test_unknown_scope_is_rejected():
    with pytest.raises(ConfigError, match="CLIENT_SCOPES"):
        parse_scopes("a:admin")


def test_gateway_needs_its_credentials():
    with pytest.raises(ConfigError, match="CF_API_TOKEN"):
        load_settings({"MODEL_PROVIDER": "gateway", "CF_ACCOUNT_ID": "acc"})


@pytest.mark.parametrize(
    "env,message",
    [
        ({"MODEL_PROVIDER": "fake", "API_KEYS": f"a:{STRONG}"}, "fake"),
        ({"API_KEYS": ""}, "vacía"),
        ({"API_KEYS": "a:short"}, "16"),
        (
            {
                "API_KEYS": f"a:{STRONG}",
                "LANGSMITH_TRACING": "true",
                "HIDE_INPUTS": "false",
            },
            "HIDE_INPUTS",
        ),
    ],
)
def test_production_compliance(env, message):
    base = {
        "ENVIRONMENT": "production",
        "MODEL_PROVIDER": "gateway",
        "CF_ACCOUNT_ID": "acc",
        "CF_API_TOKEN": "tok",
    }
    with pytest.raises(ConfigError, match=message):
        load_settings({**base, **env})


def test_production_with_everything_in_place():
    settings = load_settings(
        {
            "ENVIRONMENT": "production",
            "MODEL_PROVIDER": "gateway",
            "CF_ACCOUNT_ID": "acc",
            "CF_API_TOKEN": "tok",
            "API_KEYS": f"portal:{STRONG}",
            "LANGSMITH_TRACING": "true",
        }
    )
    assert settings.is_production
