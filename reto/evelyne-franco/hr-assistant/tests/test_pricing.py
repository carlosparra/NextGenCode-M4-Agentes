"""Pruebas unitarias de la tabla de precios.

``PriceTable.from_file(path, required)`` carga los precios en USD por
millon de tokens y exige que existan los modelos de ``required``.
``cost(model, input_tokens, output_tokens)`` no redondea.

:seealso: ``spec/03-costs.md`` y ADR 0009.
"""

import json

import pytest

from app.pricing import PriceTable
from tests.conftest import MODEL_LARGE, MODEL_SMALL


def test_cost_matches_a_hand_calculated_case(prices):
    """1000 tokens de entrada y 500 de salida del modelo pequeno:
    1000 * 0.045 / 1e6 + 500 * 0.384 / 1e6 = 0.000237 USD.
    """
    assert prices.cost(MODEL_SMALL, 1000, 500) == pytest.approx(0.000237)
    assert prices.cost(MODEL_LARGE, 1000, 500) == pytest.approx(0.0014195)


def test_tiny_costs_are_not_rounded_to_zero(prices):
    """Un solo token cuesta millonesimas de dolar y no se redondea."""
    cost = prices.cost(MODEL_SMALL, 1, 0)

    assert cost > 0
    assert cost == pytest.approx(0.045 / 1_000_000)


def test_missing_price_for_a_configured_model_stops_startup(tmp_path):
    """Si falta el precio de un modelo configurado, la carga falla y
    el mensaje dice cual.
    """
    path = tmp_path / "prices.json"
    path.write_text(
        json.dumps({"models": {MODEL_SMALL: {"input": 0.045, "output": 0.384}}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=MODEL_LARGE):
        PriceTable.from_file(str(path), (MODEL_SMALL, MODEL_LARGE))


def test_missing_prices_file_stops_startup(tmp_path):
    """Si el archivo de precios no existe, la carga falla."""
    missing = tmp_path / "does-not-exist.json"

    with pytest.raises((ValueError, FileNotFoundError)):
        PriceTable.from_file(str(missing), (MODEL_SMALL, MODEL_LARGE))
