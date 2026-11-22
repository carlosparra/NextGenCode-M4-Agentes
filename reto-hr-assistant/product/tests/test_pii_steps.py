"""Pasos de ``features/pii.feature``: redacción de PII de punta a punta en la API."""

import json

from pytest_bdd import given, parsers, scenarios, then, when

scenarios("features/pii.feature")


@given("the assistant with the simulated model", target_fixture="observed")
def assistant_with_fake_model(make_observed):
    """Aplicación con el modelo simulado y el log en memoria."""
    return make_observed()


@given(
    parsers.parse('the assistant whose model answers "{text}"'),
    target_fixture="observed",
)
def assistant_with_scripted_answer(make_observed, scripted_model, text):
    """Aplicación cuyo modelo responde siempre el texto dado."""
    model = scripted_model([json.dumps({"answer": text})])
    return make_observed(model=model)


@when(parsers.parse('I ask "{question}"'), target_fixture="response")
def ask_question(observed, question):
    """Manda la pregunta a ``POST /ask``."""
    return observed.client.post("/ask", json={"question": question})


@then("the request succeeds")
def request_succeeds(response):
    """La API responde ``200`` aunque haya PII."""
    assert response.status_code == 200


@then(parsers.parse("the redacted types are {types}"))
def redacted_types(response, types):
    """``pii_redacted`` lista solo los tipos encontrados en la pregunta."""
    assert response.json()["pii_redacted"] == json.loads(types)


@then(parsers.parse('neither the answer nor the log contain "{value}"'))
def value_never_leaks(observed, response, value):
    """El valor original no sale en la respuesta ni en el log."""
    assert value not in response.json()["answer"]
    assert value not in observed.log_text()


@then(parsers.parse('the answer is "{text}"'))
def answer_is(response, text):
    """La respuesta es exactamente el texto esperado."""
    assert response.json()["answer"] == text
