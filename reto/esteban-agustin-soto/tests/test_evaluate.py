"""Pruebas de la regla de costo y calidad, sin correr el producto."""

from contextlib import contextmanager

import pytest

from verification import evaluate

CASES = [{"question": "q", "must_include": ["Ana"]}] * 2


class FakeClient:
    """Cliente que responde siempre lo mismo, para medir sin servidor."""

    def __init__(self, answer, cost, status_code=200):
        self.answer, self.cost, self.status_code = answer, cost, status_code

    def post(self, _path, json):
        assert json["history"]
        return self

    def json(self):
        if self.status_code != 200:
            return {"detail": "model unavailable"}
        return {"answer": self.answer, "cost_usd": self.cost, "input_tokens": 10}


def test_must_include_needs_every_text():
    case = {"must_include": ["Ana", "Jorge"]}
    assert evaluate.is_correct("Ana y Jorge", case)
    assert not evaluate.is_correct("Ana", case)


def test_any_of_needs_one_text_ignoring_case():
    assert evaluate.is_correct("Ya NO EXISTE", {"any_of": ["no existe"]})


def test_measure_adds_quality_cost_and_tokens():
    assert evaluate.measure(FakeClient("Ana", 0.5), CASES) == {
        "quality": 1.0, "cost_usd": 1.0, "input_tokens": 20, "errors": 0,
    }


def test_a_failed_call_counts_as_an_error_and_as_incorrect():
    result = evaluate.measure(FakeClient("Ana", 0.5, status_code=502), CASES)
    assert result == {
        "quality": 0.0, "cost_usd": 0.0, "input_tokens": 0, "errors": 2,
    }


def test_levers_must_be_cheaper_without_losing_quality():
    baseline = {"quality": 0.9, "cost_usd": 1.0}
    assert evaluate.verdict(baseline, {"quality": 0.9, "cost_usd": 0.4})
    assert not evaluate.verdict(baseline, {"quality": 0.8, "cost_usd": 0.1})
    assert not evaluate.verdict(baseline, {"quality": 1.0, "cost_usd": 1.0})


def test_missing_credentials_names_only_the_variables():
    env = {"CF_ACCOUNT_ID": "secret-account", "CF_API_TOKEN": ""}
    assert evaluate.missing_credentials(env) == ["CF_API_TOKEN"]
    assert evaluate.missing_credentials({}) == ["CF_ACCOUNT_ID", "CF_API_TOKEN"]
    assert evaluate.missing_credentials(
        {"CF_ACCOUNT_ID": "a", "CF_API_TOKEN": "b"}
    ) == []


def test_summarize_reports_mean_and_worst_quality():
    runs = [
        {"quality": 1.0, "cost_usd": 0.2, "input_tokens": 100, "errors": 0},
        {"quality": 0.5, "cost_usd": 0.4, "input_tokens": 300, "errors": 1},
    ]
    assert evaluate.summarize(runs) == {
        "quality": 0.75, "worst_quality": 0.5, "cost_usd": pytest.approx(0.3),
        "input_tokens": 200, "errors": 1,
    }


def test_the_table_lists_every_configuration_and_the_verdict():
    summary = {
        "quality": 1.0, "worst_quality": 1.0, "cost_usd": 0.25,
        "input_tokens": 120, "errors": 0,
    }
    table = evaluate.render_report(
        {"baseline": summary, "levers": summary, "levers + cache": summary}, True
    )
    for name in ("baseline", "levers", "levers + cache"):
        assert f"| {name} |" in table
    assert "PASA" in table
    assert "NO PASA" in evaluate.render_report({"baseline": summary}, False)


def test_the_real_mode_needs_credentials_and_never_prints_them(
    monkeypatch, capsys
):
    monkeypatch.delenv("CF_ACCOUNT_ID", raising=False)
    monkeypatch.setenv("CF_API_TOKEN", "")
    assert evaluate.main(["--real"]) == 2
    out = capsys.readouterr().out
    assert "CF_ACCOUNT_ID" in out and "CF_API_TOKEN" in out


@pytest.fixture(name="fake_products")
def fake_products_fixture(monkeypatch, tmp_path):
    """Reemplaza el producto por clientes simulados y anota cómo se arrancó."""
    started = []

    @contextmanager
    def running(port, **options):
        started.append((port, options))
        yield FakeClient("Ana", 0.5 if len(started) == 1 else 0.1)

    monkeypatch.setattr(evaluate, "running_product", running)
    monkeypatch.setattr(evaluate, "load_cases", lambda: CASES)
    monkeypatch.setattr(evaluate, "REAL_REPORT", tmp_path / "evaluate-real.md")
    monkeypatch.setenv("CF_ACCOUNT_ID", "secret-account-xyz")
    monkeypatch.setenv("CF_API_TOKEN", "secret-token-xyz")
    return started


def test_the_real_mode_measures_three_configurations_with_the_gateway(
    fake_products, tmp_path
):
    assert evaluate.main(["--real"]) == 0
    assert len(fake_products) == 3
    for _port, options in fake_products:
        assert options["MODEL_PROVIDER"] == "gateway"
        assert options["timeout"] >= 60
        assert options["system_certs"] is True
    baseline, levers, cached = (options for _port, options in fake_products)
    assert baseline["ROUTING"] == "false"
    assert "ROUTING" not in levers and "CACHE_TTL_SECONDS" not in levers
    assert int(cached["CACHE_TTL_SECONDS"]) > 0
    report = (tmp_path / "evaluate-real.md").read_text(encoding="utf-8")
    assert "| baseline |" in report and "| levers + cache |" in report
    assert "secret-" not in report


def test_the_real_mode_fails_when_the_levers_are_not_cheaper(
    fake_products, monkeypatch
):
    @contextmanager
    def same_cost(port, **options):
        fake_products.append((port, options))
        yield FakeClient("Ana", 0.5)

    monkeypatch.setattr(evaluate, "running_product", same_cost)
    assert evaluate.main(["--real"]) == 1
