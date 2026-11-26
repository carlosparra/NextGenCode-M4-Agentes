"""Configuración: valores por omisión, errores claros y reglas de compliance."""

import pytest

from app.config import ConfigError, load_settings, parse_api_keys, parse_scopes

STRONG = "k" * 20
PRODUCTION = {
    "ENVIRONMENT": "production", "MODEL_PROVIDER": "gateway", "CF_ACCOUNT_ID": "acc",
    "CF_API_TOKEN": "token", "API_KEYS": f"portal:{STRONG}",
    "CLIENT_SCOPES": "portal:ask",
}


def test_defaults_are_safe_for_development():
    settings = load_settings({})
    assert settings.model_provider == "fake"
    assert settings.agent_max_steps == 3
    assert settings.hide_inputs and settings.hide_outputs
    assert settings.scopes_for("anyone") == {"ask", "mcp", "metrics"}


@pytest.mark.parametrize("env", [
    {"AGENT_MAX_STEPS": "0"},
    {"AGENT_MAX_STEPS": "many"},
    {"ROUTING": "maybe"},
    {"MODEL_PROVIDER": "other"},
    {"ENVIRONMENT": "staging"},
    {"CLIENT_SCOPES": "portal:admin"},
    {"MODEL_PROVIDER": "gateway"},
])
def test_invalid_values_refuse_to_start(env):
    with pytest.raises(ConfigError):
        load_settings(env)


def test_api_keys_error_never_shows_the_value():
    with pytest.raises(ConfigError) as error:
        parse_api_keys("good:key-value,secret-without-client")
    assert "secret-without-client" not in str(error.value)
    assert "entrada 2" in str(error.value)


def test_scopes_are_parsed_per_client():
    scopes = parse_scopes("portal:ask,ops:metrics+ask")
    assert scopes == {"portal": {"ask"}, "ops": {"metrics", "ask"}}


def test_relative_paths_resolve_inside_the_project():
    settings = load_settings({"EMPLOYEES_PATH": "data/employees.json"})
    assert settings.employees_path.is_absolute()
    assert settings.employees_path.exists()


def test_production_accepts_a_complete_configuration():
    settings = load_settings(PRODUCTION)
    assert settings.environment == "production"
    assert settings.scopes_for("portal") == {"ask"}


@pytest.mark.parametrize("change", [
    {"MODEL_PROVIDER": "fake"},
    {"API_KEYS": ""},
    {"API_KEYS": "portal:short"},
    {"CLIENT_SCOPES": ""},
    {"LANGSMITH_TRACING": "true", "HIDE_INPUTS": "false"},
])
def test_production_refuses_unsafe_configuration(change):
    with pytest.raises(ConfigError):
        load_settings({**PRODUCTION, **change})


def test_render_hostname_is_an_allowed_mcp_host():
    settings = load_settings({"RENDER_EXTERNAL_HOSTNAME": "hr.onrender.com"})
    assert settings.mcp_allowed_hosts == ("hr.onrender.com",)
