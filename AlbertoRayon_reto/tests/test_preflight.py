"""Revisión de la configuración antes de arrancar."""

from app.preflight import main


def test_preflight_accepts_the_development_defaults(capsys):
    assert main({}) == 0
    assert "[OK]" in capsys.readouterr().out


def test_preflight_explains_why_production_cannot_start(capsys):
    assert main({"ENVIRONMENT": "production"}) == 1
    assert "MODEL_PROVIDER=fake" in capsys.readouterr().err
