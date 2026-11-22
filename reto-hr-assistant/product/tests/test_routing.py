"""Pruebas del enrutador: una regla en código elige el modelo por pregunta."""

from app.config import load_settings
from app.routing import choose_model

SMALL_MODEL = "@cf/meta/llama-3.1-8b-instruct-fast"
LARGE_MODEL = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"


def test_keywords_are_found_regardless_of_case_and_accents():
    settings = load_settings({})

    shouted = choose_model("EXPLICA la política de vacaciones", settings)
    unaccented = choose_model("Por que cambió mi jefe", settings)

    assert (shouted.model, shouted.reason) == (LARGE_MODEL, "keyword:explica")
    assert unaccented.model == LARGE_MODEL
    assert unaccented.reason.startswith("keyword:")


def test_keywords_match_whole_words_so_resumen_stays_on_the_small_model():
    settings = load_settings({})

    summary = choose_model("Dame el resumen del departamento de Ventas", settings)
    resume = choose_model("resume las altas del mes", settings)

    assert (summary.model, summary.reason) == (SMALL_MODEL, "default_small")
    assert (resume.model, resume.reason) == (LARGE_MODEL, "keyword:resume")


def test_question_of_exactly_the_default_limit_stays_on_the_small_model():
    settings = load_settings({})

    at_limit = choose_model("x" * 80, settings)
    over_limit = choose_model("x" * 81, settings)

    assert (at_limit.model, at_limit.reason) == (SMALL_MODEL, "default_small")
    assert (over_limit.model, over_limit.reason) == (LARGE_MODEL, "long_question")
