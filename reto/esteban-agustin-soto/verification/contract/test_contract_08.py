"""Contrato de la sesión 8: la respuesta nunca pasa del límite de caracteres.

El producto corre con un límite muy pequeño, para que hasta una respuesta normal
se recorte. La prueba compara lo que devuelve la API con lo que queda en el log.
"""

import json
import time

LIMIT = 10
WAIT_SECONDS = 3.0
QUESTION = {"question": "¿Quién es EMP-0004?"}
ELLIPSIS = "…"


def events_of(log_path, name, request_id):
    """Eventos de un tipo que el producto escribió para una petición."""
    found = []
    for line in log_path.read_text("utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("event") == name and event.get("request_id") == request_id:
            found.append(event)
    return found


def wait_for(log_path, name, request_id):
    """Espera a que aparezca el evento en el log; devuelve la lista (puede ser vacía)."""
    deadline = time.monotonic() + WAIT_SECONDS
    while True:
        found = events_of(log_path, name, request_id)
        if found or time.monotonic() >= deadline:
            return found
        time.sleep(0.05)


def test_the_answer_is_cut_to_the_limit_and_ends_with_an_ellipsis(api_short_answers):
    client, _ = api_short_answers
    response = client.post("/ask", json=QUESTION)
    body = response.json()
    assert response.status_code == 200
    assert len(body["answer"]) == LIMIT
    assert body["answer"].endswith(ELLIPSIS)


def test_the_response_keeps_its_ten_fields_when_it_is_cut(api_short_answers):
    client, _ = api_short_answers
    body = client.post("/ask", json=QUESTION).json()
    assert set(body) == {
        "model", "route", "cached_calls", "cost_usd", "answer", "steps",
        "tools_used", "input_tokens", "output_tokens", "request_id",
    }


def test_the_cut_is_logged_with_numbers_only(api_short_answers):
    client, log_path = api_short_answers
    body = client.post("/ask", json=QUESTION).json()
    [event] = wait_for(log_path, "answer_truncated", body["request_id"])
    assert event["limit_chars"] == LIMIT
    assert isinstance(event["original_chars"], int) and event["original_chars"] > LIMIT
    # Solo números: ningún campo de texto con la respuesta
    assert not [
        key for key, value in event.items()
        if isinstance(value, str) and key not in {"ts", "service", "event",
                                                  "request_id", "client"}
    ]


def test_a_normal_limit_does_not_cut_or_log_anything(api, api_logged):
    # ``api`` corre con el límite por omisión: la respuesta normal sale entera
    body = api.post("/ask", json=QUESTION).json()
    assert len(body["answer"]) > LIMIT and not body["answer"].endswith(ELLIPSIS)
    _, log_path = api_logged
    text = log_path.read_text("utf-8", errors="replace")
    assert "answer_truncated" not in text
