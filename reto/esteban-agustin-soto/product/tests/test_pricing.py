"""Unit tests for the price table."""

import pytest

from app.pricing import PriceTable


def test_cost_is_priced_per_million_input_and_output_tokens(prices_path):
    table = PriceTable(prices_path)
    cost = table.cost("small-model", 1_000_000, 500_000, cached=False)
    assert cost == pytest.approx(1.0 + 1.0)


def test_cached_call_and_fake_model_cost_nothing(prices_path):
    table = PriceTable(prices_path)
    assert table.cost("large-model", 1000, 1000, cached=True) == 0
    assert table.cost("fake", 1000, 1000, cached=False) == 0


def test_model_without_price_is_reported_not_free(prices_path):
    table = PriceTable(prices_path)
    with pytest.raises(ValueError, match="mystery-model"):
        table.cost("mystery-model", 10, 10, cached=False)


def test_unreadable_price_file_is_reported(tmp_path):
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        PriceTable(broken)
    with pytest.raises(ValueError):
        PriceTable(tmp_path / "missing.json")
