"""Paridad entre la prueba de humo del producto y la de la fábrica.

Hay dos copias de la lógica: ``product/scripts/smoke.py`` (la que corre GitHub
Actions, autocontenida) y ``verification/production.py`` (la de la fábrica). Si se
separan, una aprobaría lo que la otra rechaza. Estas pruebas les dan las mismas
respuestas simuladas y exigen el mismo veredicto.
"""

import importlib.util
from pathlib import Path

import pytest

from tests.test_production import FAILURE_ANSWER, fake_render
from verification import production

SMOKE_PATH = Path(__file__).resolve().parent.parent / "product" / "scripts" / "smoke.py"
# Constantes que las dos copias deben tener iguales
SHARED_CONSTANTS = (
    "EMPLOYEE_NAME", "FAILURE_PREFIX", "FAKE_CURP", "FAKE_EMAIL", "PII_QUESTION",
    "DOCUMENTED_PATHS",
)
# Cada escenario es un servicio simulado distinto, con la misma forma que en
# tests/test_production.py
SCENARIOS = {
    "todo bien": {},
    "sin claves en el servicio": {"key_required": False},
    "servicio dormido": {"healthy": False},
    "mensaje fijo de fallo": {"answer": FAILURE_ANSWER},
    "sin el empleado": {"answer": "Pregúntame por un empleado (EMP-0001)."},
    "cuerpo que no es JSON": {"body": b"<html>gateway</html>"},
    "cuerpo sin answer": {"body": b'{"detail": "x"}'},
    "no enmascara datos personales": {"echo": True},
    "error con datos personales": {"pii_status": 502},
    "sin documentacion": {"schema": None},
    "esquema sin /ask": {"schema": {"paths": {"/health": {}}}},
    "esquema que no es un objeto": {"schema": "not an object"},
}


@pytest.fixture(name="product_smoke", scope="module")
def product_smoke_fixture():
    """Carga ``product/scripts/smoke.py`` por su ruta (``scripts/`` no es paquete)."""
    spec = importlib.util.spec_from_file_location("product_smoke", SMOKE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(smoke, options, capsys):
    """Corre una copia contra el servicio simulado: veredicto y líneas ``[OK]``."""
    passed = smoke(
        "https://x", "good-key", fake_render(**options)
    )
    return passed, capsys.readouterr().out.count("[OK]")


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_both_copies_reach_the_same_verdict(scenario, product_smoke, capsys):
    options = SCENARIOS[scenario]
    factory = run(production.smoke, options, capsys)
    product = run(product_smoke.smoke, options, capsys)
    assert product == factory, scenario


@pytest.mark.parametrize("name", SHARED_CONSTANTS)
def test_the_shared_constants_do_not_drift(name, product_smoke):
    assert getattr(product_smoke, name) == getattr(production, name)


def test_a_healthy_service_passes_with_six_checks_in_the_product(
    product_smoke, capsys
):
    assert product_smoke.smoke("https://x", "good-key", fake_render())
    assert capsys.readouterr().out.count("[OK]") == 6


def test_both_copies_refuse_to_run_without_the_key(
    product_smoke, monkeypatch, capsys
):
    monkeypatch.delenv("SMOKE_API_KEY", raising=False)
    assert product_smoke.main(["https://x"]) == production.main(["https://x"]) == 2
    assert "SMOKE_API_KEY" in capsys.readouterr().out
