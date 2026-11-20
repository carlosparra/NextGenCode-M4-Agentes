"""Pruebas unitarias del enrutador por regla (``app.router.choose_model``)."""

import pytest

from conftest import LARGE_MODEL, SMALL_MODEL

from app.config import load_config
from app.router import choose_model


def _choose(question, environ=None):
    """Elige el modelo para ``question`` con la configuración indicada."""
    return choose_model(question, load_config(environ or {}))


def test_question_at_the_char_limit_goes_to_the_small_model():
    assert _choose("a" * 80) == (SMALL_MODEL, "simple_question")
    assert _choose("a" * 81) == (LARGE_MODEL, "long_question")


@pytest.mark.parametrize(
    "question",
    [
        "COMPARA Ventas y Finanzas",
        "¿Por que se fue Jorge?",
        "Resume el equipo de Tecnología",
    ],
    ids=["upper_case", "without_accent", "capitalized"],
)
def test_keywords_ignore_case_and_accents(question):
    model, route = _choose(question)

    assert model == LARGE_MODEL
    assert route.startswith("keyword:")


@pytest.mark.parametrize(
    "question, route",
    [
        ("Dame un resumen de Ventas", "keyword:resume"),
        ("Quiero una explicación de las vacaciones", "keyword:explica"),
        ("Necesito analizar Finanzas", "keyword:analiza"),
        ("Lista a todos los de Ventas", "keyword:todos"),
    ],
    ids=["resumen", "explicacion", "analizar", "todos"],
)
def test_words_that_start_with_a_keyword_go_to_the_large_model(question, route):
    assert _choose(question) == (LARGE_MODEL, route)


@pytest.mark.parametrize(
    "question",
    ["¿Qué métodos de pago hay?", "¿Quién presume de EMP-0004?"],
    ids=["metodos_contains_todos", "presume_contains_resume"],
)
def test_keyword_inside_another_word_does_not_count(question):
    assert _choose(question) == (SMALL_MODEL, "simple_question")


def test_routing_disabled_always_uses_the_large_model():
    environ = {"ROUTING": "false"}

    assert _choose("Hola", environ) == (LARGE_MODEL, "routing_disabled")
