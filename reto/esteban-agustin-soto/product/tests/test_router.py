"""Unit tests for the rule-based model router."""

import pytest

from app.config import load_settings
from app.router import choose_model

KEYWORDS = ["compara", "resume", "explica", "por qué", "analiza", "todos"]


@pytest.fixture(name="settings")
def settings_fixture():
    """Configuración con nombres distintos para el modelo pequeño y el grande.

    :return: Configuración cargada.
    :rtype: app.config.Settings
    """
    return load_settings({
        "MODEL_PROVIDER": "fake",
        "MODEL_SMALL": "small-model",
        "MODEL_LARGE": "large-model",
    })


def test_every_keyword_routes_to_the_large_model(settings):
    for word in KEYWORDS:
        model, reason = choose_model(f"Please {word} the team", settings)
        assert model == "large-model", word
        assert reason == f"keyword:{word}"


def test_keywords_ignore_case_and_accents(settings):
    for question in ("ANALIZA al equipo", "Por Qué se fue", "POR QUE se fue"):
        model, reason = choose_model(question, settings)
        assert model == "large-model", question
        assert reason.startswith("keyword:")


def test_length_limit_and_routing_switch_decide_the_model(settings):
    assert choose_model("a" * 80, settings) == ("small-model", "simple")
    assert choose_model("a" * 81, settings) == ("large-model", "too_long")
    off = load_settings({"MODEL_PROVIDER": "fake", "ROUTING": "false",
                         "MODEL_SMALL": "small-model",
                         "MODEL_LARGE": "large-model"})
    assert choose_model("hi", off) == ("large-model", "routing_off")
