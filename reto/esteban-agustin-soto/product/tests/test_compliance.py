"""Unit tests for the production compliance rules and the new settings."""

import pytest

from app.compliance import check_production
from app.config import load_settings

SAFE = {
    "ENVIRONMENT": "production",
    "MODEL_PROVIDER": "gateway",
    "CF_ACCOUNT_ID": "acct",
    "CF_API_TOKEN": "cloudflare-token-value",
    "API_KEYS": "ana:0123456789abcdef",
}


def violations(**changes):
    """Revisa la configuración segura de producción con algunas variables cambiadas.

    :param changes: Variables que reemplazan a las seguras.
    :type changes: str
    :return: Violaciones encontradas.
    :rtype: list
    """
    return check_production(load_settings({**SAFE, **changes}))


def test_safe_production_setup_has_no_violations():
    assert not violations()


def test_fake_provider_is_a_violation():
    assert any("MODEL_PROVIDER" in text for text in violations(
        MODEL_PROVIDER="fake"))


def test_key_of_15_characters_fails_and_16_passes():
    assert violations(API_KEYS="ana:" + "k" * 15)
    assert not violations(API_KEYS="ana:" + "k" * 16)


def test_traces_must_hide_inputs_and_outputs():
    on = {"LANGSMITH_TRACING": "true"}
    assert any("HIDE_INPUTS" in t for t in violations(HIDE_INPUTS="false", **on))
    assert any("HIDE_OUTPUTS" in t for t in violations(HIDE_OUTPUTS="false", **on))
    assert not violations(HIDE_INPUTS="false")


def test_every_broken_rule_is_reported_without_the_key():
    short = "k" * 15
    found = violations(MODEL_PROVIDER="fake", API_KEYS=f"ana:{short}",
                       LANGSMITH_TRACING="true", HIDE_OUTPUTS="false")
    assert len(found) == 3
    assert all(short not in text for text in found)


def test_development_applies_no_rule():
    assert not check_production(load_settings({"API_KEYS": "ana:short"}))


def test_new_settings_have_safe_defaults():
    settings = load_settings({})
    assert settings.environment == "development"
    assert not settings.api_keys
    assert settings.rate_limit_per_minute == 30


@pytest.mark.parametrize("name, value", [
    ("ENVIRONMENT", "staging"),
    ("RATE_LIMIT_PER_MINUTE", "0"),
    ("RATE_LIMIT_PER_MINUTE", "many"),
])
def test_invalid_new_settings_are_rejected(name, value):
    with pytest.raises(ValueError):
        load_settings({name: value})


def test_settings_repr_hides_the_keys():
    settings = load_settings({"API_KEYS": "ana:very-secret-key-123456"})
    assert "very-secret-key-123456" not in repr(settings)
