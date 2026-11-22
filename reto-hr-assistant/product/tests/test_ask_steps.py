"""Pasos de los escenarios de ``features/ask.feature`` (pytest-bdd)."""

import re

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("features/ask.feature")

INVALID_QUESTIONS = {
    "empty": "",
    "blank": "   ",
    "too long": "a" * 2001,
}


@pytest.fixture
def responses():
    """Respuestas HTTP recibidas durante el escenario, en orden.

    :return: Lista vacía que llenan los pasos
    :rtype: list
    """
    return []


@given("the assistant is running with the default settings", target_fixture="client")
def default_client(make_client):
    """Arranca la API con la configuración por omisión."""
    return make_client()


@given(
    parsers.parse("the assistant is running with AGENT_MAX_STEPS set to {steps:d}"),
    target_fixture="client",
)
def capped_client(make_client, steps):
    """Arranca la API con un tope de vueltas distinto."""
    return make_client({"AGENT_MAX_STEPS": str(steps)})


@when(parsers.parse('I ask "{question}" with a previous turn in the history'))
def ask_with_history(client, responses, question):
    """Envía una pregunta con un turno previo que manda el cliente."""
    history = [
        {"role": "user", "content": "Hola"},
        {"role": "assistant", "content": "Hola, ¿en qué te ayudo?"},
    ]
    payload = {"question": question, "history": history}
    responses.append(client.post("/ask", json=payload))


@when(parsers.parse('I ask "{question}"'))
def ask(client, responses, question):
    """Envía una pregunta sin historial."""
    responses.append(client.post("/ask", json={"question": question}))


@when(parsers.parse("I send a question that is {kind}"))
def ask_invalid(client, responses, kind):
    """Envía una pregunta inválida del tipo indicado."""
    payload = {"question": INVALID_QUESTIONS[kind]}
    responses.append(client.post("/ask", json=payload))


@then(parsers.parse("the response status is {status:d}"))
def response_status(responses, status):
    """Comprueba el código HTTP de la última respuesta."""
    assert responses[-1].status_code == status


@then("every response has status 200")
def every_response_ok(responses):
    """Comprueba que todas las peticiones del escenario salieron bien."""
    assert len(responses) >= 2
    assert all(response.status_code == 200 for response in responses)


@then(parsers.parse('the answer mentions "{text}"'))
def answer_mentions(responses, text):
    """Comprueba que la respuesta contiene un texto."""
    assert text in responses[-1].json()["answer"]


@then(parsers.parse('the answer is "{text}"'))
def answer_is(responses, text):
    """Comprueba la respuesta exacta."""
    assert responses[-1].json()["answer"] == text


@then("the answer says the employee was not found")
def answer_says_not_found(responses):
    """Comprueba que la respuesta niega la existencia del empleado."""
    answer = responses[-1].json()["answer"].lower()
    assert re.search(r"\bno\b", answer)
    assert "jorge" not in answer


@then(parsers.parse('the tools used are "{tool}"'))
def tools_used_are(responses, tool):
    """Comprueba que se usó exactamente una herramienta."""
    assert responses[-1].json()["tools_used"] == [tool]


@then("no tools were used")
def no_tools_used(responses):
    """Comprueba que la respuesta no usó herramientas."""
    assert responses[-1].json()["tools_used"] == []


@then(parsers.parse("the agent took {steps:d} steps"))
def agent_took_steps(responses, steps):
    """Comprueba el número de vueltas del bucle."""
    assert responses[-1].json()["steps"] == steps


@then("the health check reports ok with the process id")
def health_is_ok(client):
    """Comprueba ``GET /health``."""
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert isinstance(body["pid"], int)


@then("the home page has the question, send and answer elements")
def home_page_has_form(client):
    """Comprueba que ``GET /`` sirve la página con sus tres elementos."""
    response = client.get("/")
    assert response.status_code == 200
    for test_id in ("question", "send", "answer"):
        assert f'data-testid="{test_id}"' in response.text
