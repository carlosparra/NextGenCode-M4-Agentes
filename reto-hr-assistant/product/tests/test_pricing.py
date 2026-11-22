"""Pruebas de la tabla de precios (USD por millón de tokens)."""

import io
import json

import pytest

from app.config import ConfigError, load_settings
from app.main import create_app
from app.pricing import PriceTable


def test_cost_is_priced_per_million_tokens(tmp_path):
    prices = tmp_path / "prices.json"
    content = {"currency": "USD", "models": {"tiny": {"input": 1.0, "output": 2.0}}}
    prices.write_text(json.dumps(content), encoding="utf-8")
    table = PriceTable.load(prices)

    assert table.cost_usd("tiny", 1_000_000, 500_000) == pytest.approx(2.0)
    assert table.cost_usd("tiny", 0, 0) == 0


def test_model_without_a_price_prevents_startup():
    with pytest.raises(ConfigError, match="unknown-model"):
        settings = load_settings({"MODEL_SMALL": "@cf/acme/unknown-model"})
        create_app(settings=settings, log_stream=io.StringIO())
