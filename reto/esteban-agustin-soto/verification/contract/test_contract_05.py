"""Contrato de la sesión 5: la CURP y el correo no vuelven a mostrarse.

Los datos son inventados. La prueba lee la salida del producto, guardada en un
archivo, y comprueba que ningún dato aparece en la respuesta ni en el log.
"""

import json
import time

# Datos inventados: no pertenecen a nadie, solo tienen la forma
CURP = "AAAA010101HDFBBB09"
EMAIL = "persona.prueba@example.com"
WAIT_SECONDS = 3.0


def log_events(log_path):
    """Lee los eventos JSON del log; ignora las líneas que no lo son."""
    events = []
    for line in log_path.read_text("utf-8", errors="replace").splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    return events


def asks_logged(log_path):
    """Cuenta los eventos ``request`` de ``/ask`` que ya están en el log."""
    return sum(
        1 for event in log_events(log_path)
        if event.get("event") == "request" and event.get("path") == "/ask"
    )


def ask(api_logged, payload):
    """Pregunta y espera a que el log tenga el evento de esa petición."""
    client, log_path = api_logged
    before = asks_logged(log_path)
    response = client.post("/ask", json=payload)
    deadline = time.monotonic() + WAIT_SECONDS
    while asks_logged(log_path) <= before and time.monotonic() < deadline:
        time.sleep(0.05)
    return response, log_path


def assert_no_personal_data(text):
    """Falla si el texto trae la CURP o el correo, en cualquier mayúscula."""
    lowered = text.lower()
    assert CURP.lower() not in lowered
    assert EMAIL.lower() not in lowered


def masked_events(log_path, where):
    """Eventos de auditoría ``pii_masked`` de un lugar."""
    return [
        event for event in log_events(log_path)
        if event.get("event") == "audit"
        and event.get("action") == "pii_masked"
        and event.get("where") == where
    ]


def test_a_question_with_personal_data_is_masked_in_the_answer_and_the_log(
    api_logged,
):
    payload = {"question": f"Mi CURP es {CURP} y mi correo es {EMAIL}. ¿Quién es EMP-0004?"}
    response, log_path = ask(api_logged, payload)
    assert response.status_code == 200
    assert "Jorge Díaz" in response.json()["answer"]
    assert_no_personal_data(response.text)
    assert_no_personal_data(log_path.read_text("utf-8", errors="replace"))
    [event] = masked_events(log_path, "question")
    assert (event["curp"], event["email"]) == (1, 1)


def test_the_audit_event_never_carries_the_value(api_logged):
    payload = {"question": f"Escribe a {EMAIL}. ¿Quién es EMP-0004?"}
    _, log_path = ask(api_logged, payload)
    event = masked_events(log_path, "question")[-1]
    assert set(event) >= {"action", "where", "curp", "email"}
    assert_no_personal_data(json.dumps(event))


def test_personal_data_in_the_history_is_masked(api_logged):
    payload = {
        "question": "¿Quién es EMP-0004?",
        "history": [
            {"role": "user", "content": f"mi curp es {CURP.lower()}"},
            {"role": "assistant", "content": f"anotado {EMAIL.upper()}"},
        ],
    }
    response, log_path = ask(api_logged, payload)
    assert response.status_code == 200
    assert_no_personal_data(response.text)
    assert_no_personal_data(log_path.read_text("utf-8", errors="replace"))
    [event] = masked_events(log_path, "history")
    assert (event["curp"], event["email"]) == (1, 1)


def test_a_validation_error_does_not_repeat_the_data(api_logged):
    payload = {"question": "hola", "history": [{"role": EMAIL, "content": "x"}]}
    response, log_path = ask(api_logged, payload)
    assert response.status_code == 422
    assert_no_personal_data(response.text)
    assert_no_personal_data(log_path.read_text("utf-8", errors="replace"))


def test_a_question_without_personal_data_emits_no_masking_event(api_logged):
    client, log_path = api_logged
    before = len(masked_events(log_path, "question"))
    _, log_path = ask(api_logged, {"question": "¿Quién es EMP-0004?"})
    assert len(masked_events(log_path, "question")) == before
    assert client.post("/ask", json={"question": "¿Quién es EMP-0004?"}).status_code == 200
