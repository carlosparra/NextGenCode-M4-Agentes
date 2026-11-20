"""Pruebas unitarias del enrutador y de la ventana de historial.

Palanca 1: una regla en codigo elige ``MODEL_LARGE`` si
``ROUTING=false``, si la pregunta pasa de ``ROUTER_MAX_CHARS`` o si
contiene una palabra clave; si no, ``MODEL_SMALL``. Los motivos son
``routing_disabled``, ``long_question``, ``keyword`` y
``simple_question``.

Palanca 2: al modelo solo llegan los ultimos ``HISTORY_WINDOW``
mensajes del historial.

:seealso: ``spec/03-costs.md`` y ADR 0008.
"""

from app.config import Settings
from app.routing import route_question, window_history


def test_every_keyword_routes_to_the_large_model_ignoring_case_and_accents():
    """Cada palabra clave manda al modelo grande, con mayusculas y
    con o sin acento.
    """
    settings = Settings()
    questions = [
        "Compara a EMP-0001 con EMP-0002",
        "RESUME el area de Ventas",
        "Explica el rol de EMP-0004",
        "Por qué se fue EMP-0003?",
        "Por que se fue EMP-0003?",
        "Analiza Finanzas",
        "Lista a todos en Ventas",
    ]
    for question in questions:
        route = route_question(question, settings)
        assert route.model == settings.model_large, question
        assert route.reason == "keyword", question


def test_question_at_the_char_limit_goes_small_and_one_more_char_goes_large():
    """Una pregunta de exactamente ``ROUTER_MAX_CHARS`` va al modelo
    pequeno; con un caracter mas, al grande por ser larga.
    """
    settings = Settings(router_max_chars=80)

    at_limit = route_question("x" * 80, settings)
    over_limit = route_question("x" * 81, settings)

    assert at_limit.model == settings.model_small
    assert at_limit.reason == "simple_question"
    assert over_limit.model == settings.model_large
    assert over_limit.reason == "long_question"


def test_window_history_keeps_only_the_last_messages():
    """La ventana deja los ultimos ``n`` mensajes; con 0 no deja
    ninguno y con menos mensajes que la ventana los deja todos.
    """
    history = [{"role": "user", "content": f"m{i}"} for i in range(10)]

    assert window_history(history, 6) == history[4:]
    assert not window_history(history, 0)
    assert window_history(history[:3], 6) == history[:3]
    assert not window_history([], 6)
