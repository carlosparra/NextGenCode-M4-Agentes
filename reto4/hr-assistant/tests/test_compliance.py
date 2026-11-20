"""Pruebas unitarias de las reglas de producción (``app.compliance``, ADR 0011)."""

import pytest

from conftest import PRODUCTION_ENV

from app.compliance import check_production
from app.config import ConfigError, load_config

UNSAFE_ENV = {
    "API_KEYS": "acme:short-secret,globex:globex-long-key-0001",
    "LANGSMITH_TRACING": "true",
    "HIDE_INPUTS": "false",
}


def test_every_broken_rule_is_reported_in_one_error_without_keys():
    assert check_production(load_config(PRODUCTION_ENV)) == []

    problems = check_production(load_config(UNSAFE_ENV))

    report = " ".join(problems)
    assert len(problems) == 3
    assert "MODEL_PROVIDER" in report
    assert "acme" in report and str(len("short-secret")) in report
    assert "HIDE_INPUTS" in report
    assert "short-secret" not in report
    assert "globex-long-key-0001" not in report
    with pytest.raises(ConfigError) as error:
        load_config({**UNSAFE_ENV, "ENVIRONMENT": "production"})
    assert all(problem in str(error.value) for problem in problems)


def test_production_without_tracing_does_not_require_hidden_text():
    environ = {
        **PRODUCTION_ENV,
        "LANGSMITH_TRACING": "false",
        "HIDE_INPUTS": "false",
        "HIDE_OUTPUTS": "false",
    }

    config = load_config(environ)

    assert check_production(config) == []
