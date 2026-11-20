"""Pruebas unitarias del costo por respuesta (``app.pricing``)."""

import json

import pytest

from conftest import DATA_PATH, PRICES_PATH, PRODUCT_ROOT, SMALL_MODEL, ScriptedModel

from app.config import ConfigError, load_config
from app.directory import load_directory
from app.main import create_app
from app.pricing import load_prices


def test_cost_uses_the_price_per_million_tokens(prices):
    cost = prices.cost(SMALL_MODEL, input_tokens=1000, output_tokens=100)

    assert cost == pytest.approx((1000 * 0.045 + 100 * 0.384) / 1_000_000)


def test_product_prices_are_an_exact_copy_of_the_spec_prices():
    spec_prices = PRODUCT_ROOT.parent / "spec" / "model_prices.json"
    if not spec_prices.exists():
        pytest.skip("la especificación solo existe dentro de la fábrica")

    product = json.loads(PRICES_PATH.read_text(encoding="utf-8"))
    spec = json.loads(spec_prices.read_text(encoding="utf-8"))

    assert product == spec


def test_negative_price_stops_startup(tmp_path):
    prices_file = tmp_path / "model_prices.json"
    models = {SMALL_MODEL: {"input": -1.0, "output": 0.384}}
    prices_file.write_text(json.dumps({"models": models}), encoding="utf-8")

    with pytest.raises(ConfigError, match=SMALL_MODEL):
        load_prices(prices_file)


def test_invalid_prices_file_stops_startup(tmp_path):
    broken = tmp_path / "model_prices.json"
    broken.write_text("{not json", encoding="utf-8")

    with pytest.raises(ConfigError):
        load_prices(broken)


def test_model_without_price_stops_startup(prices):
    config = load_config({"MODEL_SMALL": "@cf/unknown/model-without-price"})
    model = ScriptedModel([])
    models = {config.model_small: model, config.model_large: model}

    with pytest.raises(ConfigError, match="@cf/unknown/model-without-price"):
        create_app(
            config=config,
            models=models,
            directory=load_directory(DATA_PATH),
            prices=prices,
        )
