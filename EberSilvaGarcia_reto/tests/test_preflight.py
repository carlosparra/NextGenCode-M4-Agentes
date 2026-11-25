"""La verificación previa al arranque."""

import pytest

from app import preflight


def test_preflight_ok(monkeypatch, capsys):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("MODEL_PROVIDER", "fake")
    assert preflight.main() == 0
    assert "preflight ok" in capsys.readouterr().err


@pytest.mark.parametrize("key", ["kkkkkkkkkkkkkkkkkkkk"])
def test_preflight_blocks_bad_production(monkeypatch, capsys, key):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("MODEL_PROVIDER", "fake")
    monkeypatch.setenv("API_KEYS", f"a:{key}")
    assert preflight.main() == 1
    err = capsys.readouterr().err
    assert "fake" in err and key not in err
