"""Pruebas de la configuracion leida de variables de entorno."""

from pathlib import Path

import pytest

from app.config import ConfigError, load_settings


def test_defaults_are_used_when_the_environment_is_empty():
    settings = load_settings({})

    assert settings.model_provider == "fake"
    assert settings.agent_max_steps == 3
    assert settings.max_question_chars == 2000
    assert Path(settings.employees_path).parts[-2:] == ("data", "employees.json")


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("AGENT_MAX_STEPS", "0"),
        ("AGENT_MAX_STEPS", "three"),
        ("MODEL_PROVIDER", "openai"),
    ],
)
def test_invalid_value_prevents_startup_with_a_clear_message(
    employees_file, variable, value
):
    environment = {"EMPLOYEES_PATH": str(employees_file), variable: value}

    with pytest.raises(ConfigError) as error:
        load_settings(environment)

    assert variable in str(error.value)


def test_observability_settings_have_safe_defaults():
    settings = load_settings({})

    assert settings.service_name == "hr-assistant"
    assert settings.slo_p95_ms == 2000
    assert settings.langsmith_tracing is False
    assert settings.hide_inputs is True
    assert settings.hide_outputs is True
    assert settings.langsmith_enabled is False


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("SLO_P95_MS", "0"),
        ("SLO_P95_MS", "-5"),
        ("SLO_P95_MS", "fast"),
        ("LANGSMITH_TRACING", "yes"),
        ("HIDE_INPUTS", "maybe"),
        ("SERVICE_NAME", "   "),
    ],
)
def test_invalid_observability_value_prevents_startup(
    employees_file, variable, value
):
    environment = {"EMPLOYEES_PATH": str(employees_file), variable: value}

    with pytest.raises(ConfigError) as error:
        load_settings(environment)

    assert variable in str(error.value)


def test_tracing_needs_a_key_and_the_key_is_never_exposed(employees_file):
    base = {"EMPLOYEES_PATH": str(employees_file), "LANGSMITH_TRACING": "TRUE"}
    secret = "lsv2-very-secret-key"

    without_key = load_settings(base)
    with_key = load_settings({**base, "LANGSMITH_API_KEY": secret})
    with pytest.raises(ConfigError) as error:
        load_settings({**base, "LANGSMITH_API_KEY": secret, "HIDE_OUTPUTS": "nope"})

    assert without_key.langsmith_enabled is False
    assert with_key.langsmith_enabled is True
    assert secret not in repr(with_key)
    assert secret not in str(error.value)


def test_missing_employees_file_prevents_startup(tmp_path):
    missing = tmp_path / "missing.json"

    with pytest.raises(ConfigError) as error:
        load_settings({"EMPLOYEES_PATH": str(missing)})

    assert "EMPLOYEES_PATH" in str(error.value)
