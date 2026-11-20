"""Pruebas de la palanca 5: cache de respuestas en memoria (reto)."""

from conftest import (
    LARGE_MODEL,
    SMALL_MODEL,
    ManualClock,
    ScriptedLLM,
    build_client,
)
from app.cache import ResponseCache, cache_key

QUESTION = "¿Quién es EMP-0004?"
HISTORY = [{"role": "user", "content": "Hola"}]


def test_an_expired_entry_is_a_miss():
    clock = ManualClock()
    cache = ResponseCache(max_entries=2, ttl_seconds=10, clock=clock)
    key = cache_key(QUESTION, SMALL_MODEL, [])
    cache.put(key, {"answer": "Jorge Díaz"})

    assert cache.get(key) == {"answer": "Jorge Díaz"}
    clock.advance(11)
    assert cache.get(key) is None


def test_the_least_recently_used_entry_is_evicted():
    cache = ResponseCache(max_entries=2, ttl_seconds=60, clock=ManualClock())
    first, second, third = (cache_key(q, SMALL_MODEL, []) for q in ("a", "b", "c"))
    cache.put(first, "A")
    cache.put(second, "B")

    cache.get(first)
    cache.put(third, "C")

    assert cache.get(first) == "A"
    assert cache.get(second) is None
    assert cache.get(third) == "C"


def test_the_cache_key_depends_on_question_model_and_history_window():
    key = cache_key(QUESTION, SMALL_MODEL, [])

    assert cache_key("  ¿quién es emp-0004?  ", SMALL_MODEL, []) == key
    assert cache_key(QUESTION, LARGE_MODEL, []) != key
    assert cache_key(QUESTION, SMALL_MODEL, HISTORY) != key
    assert cache_key("¿Quién es EMP-0005?", SMALL_MODEL, []) != key


def test_personal_data_and_blocked_outputs_are_never_cached(
    make_settings, directory, clock, log_stream
):
    settings = make_settings(RESPONSE_CACHE_TTL_SECONDS="300")
    cases = {
        "Mi correo es ana.lopez@example.com": '{"answer": "Listo"}',
        QUESTION: '{"answer": "Usa Bearer abc123secrettoken"}',
    }
    for question, model_output in cases.items():
        llm = ScriptedLLM([model_output])
        client = build_client(
            settings, llm, directory, clock=clock, log_stream=log_stream
        )

        bodies = [client.post("/ask", json={"question": question}).json()]
        bodies.append(client.post("/ask", json={"question": question}).json())

        assert [body["cache"] for body in bodies] == ["miss", "miss"], question
        assert len(llm.calls) == 2, question
