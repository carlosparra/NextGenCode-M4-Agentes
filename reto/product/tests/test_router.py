"""Pruebas de la regla de enrutamiento por pregunta (palanca 1)."""

import pytest

from conftest import LARGE_MODEL, SMALL_MODEL
from app.router import route


@pytest.mark.parametrize(
    "question",
    [
        "Compara Ventas y Finanzas",
        "RESUME el departamento de Ventas",
        "Explica el puesto de EMP-0001",
        "¿Por qué EMP-0003 está de baja?",
        "por que EMP-0003 esta de baja",
        "ANALIZA Tecnología",
        "Dame todos los de Ventas",
    ],
)
def test_keyword_sends_the_question_to_the_large_model(make_settings, question):
    chosen = route(question, make_settings())

    assert chosen.model == LARGE_MODEL
    assert chosen.reason.startswith("keyword:")


def test_keyword_with_accent_and_capitals_is_reported_without_them(make_settings):
    chosen = route("¿POR QUÉ EMP-0003 está de baja?", make_settings())

    assert (chosen.model, chosen.reason) == (LARGE_MODEL, "keyword:por que")


def test_short_question_without_keywords_goes_to_the_small_model(make_settings):
    chosen = route("¿Quién es EMP-0004?", make_settings())

    assert (chosen.model, chosen.reason) == (SMALL_MODEL, "default_small")


def test_disabled_routing_wins_over_every_other_rule(make_settings):
    chosen = route("Compara " + "x" * 100, make_settings(ROUTING="false"))

    assert (chosen.model, chosen.reason) == (LARGE_MODEL, "routing_disabled")


def test_question_longer_than_the_limit_goes_to_the_large_model(make_settings):
    settings = make_settings(ROUTER_MAX_CHARS="80")

    at_limit = route("x" * 80, settings)
    over_limit = route("x" * 81, settings)

    assert (at_limit.model, at_limit.reason) == (SMALL_MODEL, "default_small")
    assert (over_limit.model, over_limit.reason) == (LARGE_MODEL, "long_question")
