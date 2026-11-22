"""Pruebas unitarias de la configuración por variables de entorno."""

from dataclasses import asdict
from pathlib import Path

import pytest

from app.config import ConfigError, load_settings
from app.directory import EmployeeDirectory

PRODUCT_ROOT = Path(__file__).resolve().parent.parent


def test_default_settings_are_used_when_environment_is_empty():
    settings = load_settings({})

    assert settings.model_provider == "fake"
    assert settings.agent_max_steps == 3
    assert settings.max_question_chars == 2000
    expected = PRODUCT_ROOT / "data" / "employees.json"
    assert Path(settings.employees_path).resolve() == expected.resolve()


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("AGENT_MAX_STEPS", "0"),
        ("MAX_QUESTION_CHARS", "abc"),
        ("MODEL_PROVIDER", "otro"),
        ("SLO_P95_MS", "0"),
        ("HIDE_INPUTS", "quizas"),
        ("RATE_LIMIT_PER_MINUTE", "0"),
        ("ENVIRONMENT", "staging"),
    ],
)
def test_invalid_setting_prevents_startup_naming_the_variable(variable, value):
    with pytest.raises(ConfigError) as error:
        load_settings({variable: value})

    assert variable in str(error.value)


def test_observability_settings_have_safe_defaults_and_never_keep_the_api_key():
    secret = "lsv2-test-secret-key"

    without_key = load_settings({})
    with_key = load_settings(
        {"LANGSMITH_TRACING": "true", "LANGSMITH_API_KEY": secret}
    )

    assert without_key.service_name == "hr-assistant"
    assert without_key.slo_p95_ms == 2000
    assert without_key.langsmith_tracing is False
    assert without_key.hide_inputs is True
    assert without_key.hide_outputs is True
    assert without_key.tracing_enabled is False
    assert with_key.tracing_enabled is True
    assert secret not in repr(with_key)
    assert secret not in repr(asdict(with_key))


def test_api_keys_are_read_per_client_and_never_shown():
    defaults = load_settings({})
    settings = load_settings(
        {
            "API_KEYS": " alice : key-alice-123 , bob:key-bob-456 ",
            "RATE_LIMIT_PER_MINUTE": "5",
            "ENVIRONMENT": "production",
        }
    )

    assert defaults.environment == "development"
    assert isinstance(defaults.api_keys, dict)
    assert not defaults.api_keys
    assert defaults.rate_limit_per_minute == 30
    revealed = {client: key.reveal() for client, key in settings.api_keys.items()}
    assert revealed == {"alice": "key-alice-123", "bob": "key-bob-456"}
    assert settings.rate_limit_per_minute == 5
    assert settings.environment == "production"
    assert "key-alice-123" not in repr(settings)
    assert "key-alice-123" not in repr(asdict(settings))


@pytest.mark.parametrize(
    ("raw", "entry", "length", "secret"),
    [
        ("alice:key-alice-123,missing-colon-secret", 2, 20, "missing-colon-secret"),
        (":key-without-client", 1, 19, "key-without-client"),
        ("alice:key-one-1234,alice:key-two-5678", 2, 18, "key-two-5678"),
    ],
    ids=["missing colon", "empty client", "repeated client"],
)
def test_malformed_api_keys_report_the_entry_and_its_length_but_never_its_value(
    raw, entry, length, secret
):
    with pytest.raises(ConfigError) as error:
        load_settings({"API_KEYS": raw})

    message = str(error.value)
    assert "API_KEYS" in message
    assert f"entry {entry}" in message
    assert f"{length} characters" in message
    assert secret not in message
    assert "key-alice-123" not in message
    assert "key-one-1234" not in message


def test_missing_employees_file_prevents_startup(tmp_path):
    missing = tmp_path / "missing.json"

    with pytest.raises(ConfigError) as error:
        load_settings({"EMPLOYEES_PATH": str(missing)})

    assert "EMPLOYEES_PATH" in str(error.value)


def test_employees_file_with_invalid_json_prevents_startup(tmp_path):
    broken = tmp_path / "employees.json"
    broken.write_text("{ not json", encoding="utf-8")

    with pytest.raises(ConfigError) as error:
        EmployeeDirectory(broken)

    assert "EMPLOYEES_PATH" in str(error.value)


def test_employees_file_that_is_not_a_list_of_objects_prevents_startup(tmp_path):
    wrong_shape = tmp_path / "employees.json"
    wrong_shape.write_text('{"id": "EMP-0001"}', encoding="utf-8")

    with pytest.raises(ConfigError) as error:
        EmployeeDirectory(wrong_shape)

    assert "EMPLOYEES_PATH" in str(error.value)
