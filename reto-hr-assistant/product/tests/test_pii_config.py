"""Pruebas de las variables nuevas ``PII_REDACTION`` y ``MAX_ANSWER_CHARS``."""

import pytest

from app.config import ConfigError, load_settings


def test_pii_settings_have_safe_defaults_and_reject_invalid_values():
    settings = load_settings({})

    assert settings.pii_redaction is True
    assert settings.max_answer_chars == 1500
    for name, value in (
        ("PII_REDACTION", "maybe"),
        ("MAX_ANSWER_CHARS", "0"),
        ("MAX_ANSWER_CHARS", "mucho"),
    ):
        with pytest.raises(ConfigError, match=name):
            load_settings({name: value})
