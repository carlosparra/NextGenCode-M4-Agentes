"""Pasos de los escenarios de features/ask.feature."""

import json

from conftest import BASE_FIELDS, TEST_API_KEYS, ScriptedLLM, keyed_client
from pytest_bdd import given, parsers, scenarios, then, when

from app.config import load_settings
from app.main import create_app

scenarios("features/ask.feature")


@given(
    parsers.re(r"a model that always asks for a tool and a cap of (?P<cap>\d+) steps"),
    target_fixture="client",
)
def client_with_a_model_that_never_answers(cap, employees_file, directory):
    """Construye la app con un modelo que siempre pide una herramienta."""
    settings = load_settings(
        {
            "EMPLOYEES_PATH": str(employees_file),
            "AGENT_MAX_STEPS": cap,
            "API_KEYS": TEST_API_KEYS,
        }
    )
    request = {"tool": "get_employee", "args": {"employee_id": "EMP-0004"}}
    llm = ScriptedLLM([json.dumps(request)])
    app = create_app(settings=settings, llm=llm, directory=directory)
    return keyed_client(app)


@when(parsers.re(r'I ask "(?P<question>[^"]*)"$'), target_fixture="response")
def ask_question(client, question):
    """Envia la pregunta sin historial."""
    return client.post("/ask", json={"question": question})


@when(
    parsers.re(r"I ask a question of (?P<length>\d+) characters"),
    target_fixture="response",
)
def ask_long_question(client, length):
    """Envia una pregunta del largo indicado."""
    return client.post("/ask", json={"question": "a" * int(length)})


@when(
    parsers.re(
        r'I ask "(?P<question>[^"]*)" with a history entry from role '
        r'"(?P<role>[^"]*)"'
    ),
    target_fixture="response",
)
def ask_with_history(client, question, role):
    """Envia la pregunta con un historial de una entrada."""
    history = [{"role": role, "content": "Hola"}]
    return client.post("/ask", json={"question": question, "history": history})


@then(parsers.re(r"the response status is (?P<status>\d+)"))
def response_status_is(response, status):
    """Comprueba el codigo HTTP."""
    assert response.status_code == int(status)


@then(parsers.re(r'the answer mentions "(?P<text>[^"]*)"'))
def answer_mentions(response, text):
    """Comprueba que la respuesta contiene el texto."""
    assert text in response.json()["answer"]


@then(parsers.re(r'the answer does not mention "(?P<text>[^"]*)"'))
def answer_does_not_mention(response, text):
    """Comprueba que la respuesta no contiene el texto."""
    assert text not in response.json()["answer"]


@then(parsers.re(r'the answer is "(?P<text>[^"]*)"'))
def answer_is(response, text):
    """Comprueba la respuesta exacta."""
    assert response.json()["answer"] == text


@then(parsers.re(r'the tools used are "(?P<tool>[^"]*)"'))
def tools_used_are(response, tool):
    """Comprueba que se uso exactamente una herramienta."""
    assert response.json()["tools_used"] == [tool]


@then("no tools were used")
def no_tools_were_used(response):
    """Comprueba que no se uso ninguna herramienta."""
    assert response.json()["tools_used"] == []


@then("the response reports the token usage")
def response_reports_token_usage(response):
    """Comprueba el esquema completo y que los tokens son positivos."""
    body = response.json()
    assert set(body) == BASE_FIELDS
    assert body["input_tokens"] > 0
    assert body["output_tokens"] > 0


@then(parsers.re(r"the agent took (?P<steps>\d+) steps"))
def agent_took_steps(response, steps):
    """Comprueba el numero de vueltas del bucle."""
    assert response.json()["steps"] == int(steps)
