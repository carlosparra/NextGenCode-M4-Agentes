"""Pruebas de la tabla de precios por modelo."""

import pytest

from conftest import LARGE_MODEL, SMALL_MODEL
from app.pricing import PriceTable, UnknownModelError


def test_one_million_tokens_cost_the_table_price(prices_file):
    table = PriceTable.load(prices_file)

    assert table.cost(SMALL_MODEL, 1_000_000, 0) == pytest.approx(0.045)
    assert table.cost(LARGE_MODEL, 0, 1_000_000) == pytest.approx(2.253)
    assert table.cost(SMALL_MODEL, 1000, 100) == pytest.approx(0.0000834)
    assert table.cost("fake", 1_000_000, 1_000_000) == 0


def test_unknown_model_is_rejected(prices_file):
    table = PriceTable.load(prices_file)

    with pytest.raises(UnknownModelError):
        table.cost("@cf/unknown/model", 10, 10)


@pytest.mark.parametrize("content", [None, "{not json", '{"models": []}'])
def test_missing_or_invalid_prices_file_is_rejected(tmp_path, content):
    path = tmp_path / "prices.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")

    with pytest.raises((OSError, ValueError)):
        PriceTable.load(path)
