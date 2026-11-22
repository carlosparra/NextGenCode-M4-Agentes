"""Pruebas de la configuración ``MAX_ANSWER_CHARS`` (sesión 8)."""

import pytest

from conftest import ANA_KEY
from app.compliance import check_production
from app.config import load_settings
from app.main import create_app

PRODUCTION = {
    "ENVIRONMENT": "production", "MODEL_PROVIDER": "gateway",
    "API_KEYS": f"ana:{ANA_KEY}", "CF_ACCOUNT_ID": "account-1",
    "CF_API_TOKEN": "gateway-token-9",
}


def test_default_answer_limit_is_1500():
    assert load_settings({}).max_answer_chars == 1500


def test_a_valid_answer_limit_is_respected():
    assert load_settings({"MAX_ANSWER_CHARS": "200"}).max_answer_chars == 200


@pytest.mark.parametrize("value", ["0", "-5", "abc", "1.5", ""])
def test_an_invalid_answer_limit_stops_startup_and_names_the_variable(value):
    with pytest.raises(ValueError, match="MAX_ANSWER_CHARS"):
        load_settings({"MAX_ANSWER_CHARS": value})


def test_production_starts_without_the_variable_and_compliance_ignores_it(
    employees_path,
):
    settings = load_settings({**PRODUCTION, "EMPLOYEES_PATH": str(employees_path)})
    assert not check_production(settings)
    assert create_app(settings=settings, models={
        settings.model_small: object(), settings.model_large: object(),
    }) is not None


def test_settings_repr_still_hides_the_keys():
    settings = load_settings({"API_KEYS": "ana:very-secret-key-123456"})
    assert "very-secret-key-123456" not in repr(settings)
    assert "max_answer_chars=1500" in repr(settings)
