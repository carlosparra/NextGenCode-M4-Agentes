"""Pruebas de ``POST /ask`` con el límite de tamaño de la respuesta (sesión 8).

Todo sin red y con datos ficticios: la CURP y el correo son inventados.
"""

import json

import pytest

from conftest import (
    AUTH_HEADERS, ScriptedModel, answer_json, log_lines,
)
from app.llm import ModelUnavailable
from app.pii import mask_text
from app.truncate import ELLIPSIS

CURP = "AAAA010101HDFBBB09"
EMAIL = "persona.prueba@example.com"
TEN_FIELDS = {
    "model", "route", "cached_calls", "cost_usd", "answer", "steps",
    "tools_used", "input_tokens", "output_tokens", "request_id",
}
QUESTION = {"question": "Who is EMP-0004?"}


class FailingModel:
    """Modelo simulado que siempre dice que el modelo real no responde."""

    def complete(self, messages):
        """Falla como lo haría el gateway.

        :param messages: Mensajes que recibe el modelo.
        :type messages: list
        :raises ModelUnavailable: Siempre.
        """
        raise ModelUnavailable("ConnectTimeout")


def long_text(size):
    """Construye un texto distinguible de ``size`` caracteres.

    :param size: Largo exacto del texto.
    :type size: int
    :return: Palabras numeradas, sin datos personales.
    :rtype: str
    """
    words = "".join(f"w{number:05d} " for number in range(size // 7 + 1))
    return words[:size]


def ask(make_observed_client, text, **env):
    """Pregunta con un modelo que contesta ``text`` y devuelve todo lo útil.

    :param make_observed_client: Fábrica de clientes con bitácora.
    :type make_observed_client: collections.abc.Callable
    :param text: Respuesta que da el modelo simulado.
    :type text: str
    :param env: Variables de entorno extra (por ejemplo ``MAX_ANSWER_CHARS``).
    :type env: str
    :return: Respuesta HTTP, bitácora como texto y el modelo usado.
    :rtype: tuple
    """
    model = ScriptedModel([answer_json(text)])
    client, stream = make_observed_client(model=model, env=env)
    return client.post("/ask", json=QUESTION), stream, model


def events(stream, name):
    """Filtra las líneas de la bitácora por nombre de evento.

    :param stream: Flujo con la bitácora.
    :type stream: io.StringIO
    :param name: Nombre del evento.
    :type name: str
    :return: Entradas con ese evento.
    :rtype: list
    """
    return [line for line in log_lines(stream) if line["event"] == name]


def test_long_answer_is_cut_to_the_default_limit_with_an_ellipsis(
    make_observed_client,
):
    response, _, _ = ask(make_observed_client, long_text(5000))
    body = response.json()
    assert response.status_code == 200
    assert set(body) == TEN_FIELDS
    assert len(body["answer"]) == 1500
    assert body["answer"].endswith(ELLIPSIS)
    assert body["answer"][:-1] == long_text(5000)[:1499]


def test_cutting_does_not_change_tokens_cost_or_the_rest_of_the_response(
    make_observed_client,
):
    cut, _, _ = ask(make_observed_client, long_text(5000), MAX_ANSWER_CHARS="200")
    whole, _, _ = ask(make_observed_client, long_text(5000),
                      MAX_ANSWER_CHARS="9000")
    others = TEN_FIELDS - {"answer", "request_id"}
    assert len(whole.json()["answer"]) == 5000
    assert {k: cut.json()[k] for k in others} == {k: whole.json()[k] for k in others}


@pytest.mark.parametrize("size, is_cut", [(1500, False), (1501, True)])
def test_answer_at_the_limit_is_intact_and_one_more_is_cut(
    make_observed_client, size, is_cut
):
    response, stream, _ = ask(make_observed_client, long_text(size))
    answer = response.json()["answer"]
    assert len(answer) == 1500
    assert (answer == long_text(size)) is not is_cut
    assert bool(events(stream, "answer_truncated")) is is_cut


def test_short_answer_emits_no_truncation_event(make_observed_client):
    response, stream, _ = ask(make_observed_client, "EMP-0004 is Jorge Diaz.")
    assert response.json()["answer"] == "EMP-0004 is Jorge Diaz."
    assert not events(stream, "answer_truncated")


def test_curp_crossing_the_cut_point_leaves_no_part_of_it(make_observed_client):
    text = "a" * 94 + " " + CURP + " tail"
    response, _, _ = ask(make_observed_client, text, MAX_ANSWER_CHARS="100")
    answer = response.json()["answer"]
    assert len(answer) == 100
    assert answer == "a" * 94 + " [CUR" + ELLIPSIS
    assert CURP[:5] not in answer


def test_email_crossing_the_cut_point_leaves_no_part_of_it(make_observed_client):
    text = "b" * 92 + " " + EMAIL + " tail"
    response, _, _ = ask(make_observed_client, text, MAX_ANSWER_CHARS="100")
    answer = response.json()["answer"]
    assert len(answer) == 100
    assert answer == "b" * 92 + " [EMAIL" + ELLIPSIS
    assert "persona" not in answer and "example" not in answer


def test_cut_still_applies_when_pii_masking_is_off(make_observed_client):
    response, stream, _ = ask(
        make_observed_client, long_text(300),
        MAX_ANSWER_CHARS="100", PII_MASKING="false",
    )
    answer = response.json()["answer"]
    assert response.status_code == 200
    assert len(answer) == 100 and answer.endswith(ELLIPSIS)
    assert len(events(stream, "answer_truncated")) == 1


def test_truncation_event_has_only_the_two_counts(make_observed_client):
    text = long_text(5000)
    _, stream, _ = ask(make_observed_client, text)
    found = events(stream, "answer_truncated")
    assert len(found) == 1
    entry = found[0]
    assert entry["original_chars"] == 5000
    assert entry["limit_chars"] == 1500
    extra = set(entry) - {"original_chars", "limit_chars"}
    assert extra <= {"event", "ts", "service", "request_id", "client"}


def test_original_chars_is_the_length_after_masking(make_observed_client):
    text = "x" * 60 + " " + EMAIL + " " + "y" * 60
    _, stream, _ = ask(make_observed_client, text, MAX_ANSWER_CHARS="100")
    entry = events(stream, "answer_truncated")[0]
    assert len(mask_text(text)) < len(text)
    assert entry["original_chars"] == len(mask_text(text))
    assert entry["limit_chars"] == 100


def test_log_never_contains_the_cut_text_or_a_piece_of_it(make_observed_client):
    text = long_text(5000)
    _, stream, _ = ask(make_observed_client, text)
    raw = stream.getvalue()
    assert "answer_truncated" in raw
    for start in (0, 700, 1480, 1481, 3000, 4980):
        assert text[start:start + 20] not in raw


def test_limit_of_one_answers_with_just_the_ellipsis(make_observed_client):
    response, stream, _ = ask(
        make_observed_client, "A normal answer.", MAX_ANSWER_CHARS="1"
    )
    assert response.status_code == 200
    assert response.json()["answer"] == ELLIPSIS
    assert events(stream, "answer_truncated")[0]["limit_chars"] == 1


def test_cutting_adds_no_model_call_and_no_second_agent_run(
    make_observed_client,
):
    _, stream, model = ask(make_observed_client, long_text(5000))
    _, other_stream, other_model = ask(
        make_observed_client, long_text(5000), MAX_ANSWER_CHARS="9000"
    )
    assert len(model.calls) == len(other_model.calls) == 1
    assert len(events(stream, "agent_run")) == 1
    assert len(events(other_stream, "agent_run")) == 1


def test_model_failure_is_still_a_502_and_is_not_cut(make_observed_client):
    client, _ = make_observed_client(
        model=FailingModel(), env={"MAX_ANSWER_CHARS": "1"}
    )
    response = client.post("/ask", json=QUESTION)
    body = response.json()
    assert response.status_code == 502
    assert body["detail"] == "model unavailable"
    assert body["request_id"]


def test_missing_key_is_still_a_401_and_the_rate_limit_a_429(
    make_secure_client,
):
    client, _, _ = make_secure_client(
        env={"MAX_ANSWER_CHARS": "1", "RATE_LIMIT_PER_MINUTE": "1"}
    )
    missing = client.post("/ask", json=QUESTION)
    assert missing.status_code == 401
    assert missing.json() == {"detail": "invalid or missing API key"}
    assert client.post("/ask", json=QUESTION, headers=AUTH_HEADERS).status_code == 200
    limited = client.post("/ask", json=QUESTION, headers=AUTH_HEADERS)
    assert limited.status_code == 429
    assert limited.json() == {"detail": "rate limit exceeded"}


def test_ask_response_schema_keeps_ten_properties_and_documents_the_limit(
    make_secure_client,
):
    client, _, _ = make_secure_client()
    schema = client.get("/openapi.json").json()
    ask_response = schema["components"]["schemas"]["AskResponse"]
    answer = ask_response["properties"]["answer"]
    assert set(ask_response["properties"]) == TEN_FIELDS
    assert "1500" in answer["description"]
    assert ELLIPSIS in answer["description"]
    assert "maxLength" not in answer
    text = json.dumps(schema, ensure_ascii=False)
    assert "ana-key" not in text and mask_text(text) == text
