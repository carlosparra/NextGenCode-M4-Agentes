"""Pruebas de ``search_policy`` (spec 06, punto 2).

La herramienta busca un tema sin acentos ni mayusculas, por ``topic`` o
por cualquiera de sus ``keywords``. Un tema que no existe devuelve la
lista de temas. Un argumento invalido no llama a la herramienta y deja
``security`` con ``control=tool_args``.
"""

from app.llm import TOOL_RESULT_PREFIX
from tests.conftest import (
    POLICY_TOPICS,
    SAMPLE_POLICIES,
    VACATION_TEXT,
    RecordingTracer,
    SpyModel,
)


def test_search_policy_finds_a_topic_by_its_name(policy_book):
    """``aguinaldo`` devuelve su tema y su texto."""
    result = policy_book.search_policy("aguinaldo")

    assert result == {"topic": "aguinaldo", "text": SAMPLE_POLICIES[2]["text"]}


def test_search_policy_finds_a_topic_by_keyword_without_accents_or_case(
    policy_book,
):
    """``DÍAS LIBRES`` es palabra clave del tema ``vacaciones``."""
    result = policy_book.search_policy("DÍAS LIBRES")

    assert result == {"topic": "vacaciones", "text": VACATION_TEXT}


def test_an_unknown_policy_topic_lists_the_available_topics(policy_book):
    """Un tema inexistente devuelve el error y todos los temas."""
    result = policy_book.search_policy("bonos de productividad")

    assert result["error"] == "tema no encontrado"
    assert sorted(result["topics"]) == sorted(POLICY_TOPICS)
    assert "text" not in result


def test_an_invalid_policy_topic_never_reaches_the_tool(build_harness):
    """Vacio, de 61 caracteres o un numero: no se busca y se audita.

    La pregunta trae ``vacaciones``, asi que el producto consulta la
    politica una vez en codigo; despues el modelo pide tres temas
    invalidos y ninguno llega a ``search_policy``.
    """
    tracer = RecordingTracer()
    spy = SpyModel(
        replies=[
            {"tool": "search_policy", "args": {"topic": ""}},
            {"tool": "search_policy", "args": {"topic": "x" * 61}},
            {"tool": "search_policy", "args": {"topic": 42}},
            {"answer": "Listo."},
        ]
    )
    harness = build_harness(model=spy, max_steps=4, tracer=tracer)

    response = harness.client.post(
        "/ask", json={"question": "¿Cuántos días de vacaciones tengo?"}
    )

    assert response.status_code == 200
    controls = [e["control"] for e in harness.events("security")]
    assert controls == ["tool_args", "tool_args", "tool_args"]
    # Solo la consulta en codigo llego a la herramienta.
    assert len(tracer.named("search_policy")) == 1
    # El modelo leyo un error por cada tema invalido, sin el valor.
    tool_results = [
        m["content"]
        for m in spy.specialist_calls[-1]
        if m.get("content", "").startswith(TOOL_RESULT_PREFIX)
        and "error" in m["content"]
    ]
    assert len(tool_results) == 3
    assert all("x" * 61 not in text for text in tool_results)
