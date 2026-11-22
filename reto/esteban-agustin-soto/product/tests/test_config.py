"""Unit tests for app.config."""

import pytest

from app.config import load_settings


def test_defaults_are_used_when_nothing_is_set():
    settings = load_settings({})
    assert settings.model_provider == "fake"
    assert settings.agent_max_steps == 3
    assert settings.max_question_chars == 2000
    assert str(settings.employees_path).endswith("employees.json")


def test_environment_values_override_defaults(employees_path):
    settings = load_settings({
        "AGENT_MAX_STEPS": "5",
        "MAX_QUESTION_CHARS": "100",
        "EMPLOYEES_PATH": str(employees_path),
    })
    assert settings.agent_max_steps == 5
    assert settings.max_question_chars == 100


@pytest.mark.parametrize(
    "env",
    [
        {"AGENT_MAX_STEPS": "0"},
        {"AGENT_MAX_STEPS": "many"},
        {"MAX_QUESTION_CHARS": "-1"},
        {"MODEL_PROVIDER": "unknown"},
    ],
)
def test_invalid_values_prevent_startup(env):
    with pytest.raises(ValueError):
        load_settings(env)
