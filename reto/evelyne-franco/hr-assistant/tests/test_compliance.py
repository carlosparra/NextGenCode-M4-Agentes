"""Pruebas unitarias de las reglas de compliance (``app.compliance``).

``production_violations(settings)`` lista las reglas que fallan y
``enforce(settings)`` lanza ``ComplianceError`` con sus nombres, nunca
con valores. Cada regla por separado ya la cubre
``features/production.feature``.
"""

import pytest

from app.compliance import ComplianceError, enforce, production_violations
from app.config import load_settings


def test_development_has_no_compliance_rules():
    """En ``development`` el modelo simulado y sin claves es valido."""
    settings = load_settings({"ENVIRONMENT": "development"})

    assert not production_violations(settings)
    enforce(settings)


def test_every_production_violation_is_reported_without_values():
    """Modelo simulado, clave corta y trazas que muestran salidas: tres
    reglas fallan y el error no muestra la clave.
    """
    short_key = "short-secret"
    settings = load_settings(
        {
            "ENVIRONMENT": "production",
            "MODEL_PROVIDER": "fake",
            "API_KEYS": f"acme:{short_key}",
            "LANGSMITH_TRACING": "true",
            "HIDE_OUTPUTS": "false",
        }
    )

    assert len(production_violations(settings)) == 3
    with pytest.raises(ComplianceError) as error:
        enforce(settings)
    assert short_key not in str(error.value)
