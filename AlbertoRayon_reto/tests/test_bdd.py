"""Escenarios Gherkin del comportamiento del HR Assistant."""

from pytest_bdd import given, parsers, scenarios, then, when

scenarios("features/hr_assistant.feature")


@given("el HR Assistant con el modelo simulado", target_fixture="context")
def assistant(client):
    return {"client": client}


@when(parsers.parse('pregunto "{question}"'))
def ask(context, question):
    context["response"] = context["client"].post("/ask", json={"question": question})


@when(parsers.parse('pregunto sin clave "{question}"'))
def ask_without_key(context, question):
    context["response"] = context["client"].post(
        "/ask", json={"question": question}, headers={"X-API-Key": ""}
    )


@then(parsers.parse('la respuesta menciona "{text}"'))
def answer_mentions(context, text):
    assert text in context["response"].json()["answer"]


@then(parsers.parse('responde el agente "{agent}"'))
def answered_by(context, agent):
    assert context["response"].json()["agent"] == agent


@then(parsers.parse('el razonamiento menciona "{text}"'))
def reasoning_mentions(context, text):
    assert text in context["response"].json()["reasoning"]


@then(parsers.parse('se ocultó el dato "{kind}"'))
def data_was_masked(context, kind):
    assert kind in context["response"].json()["pii_masked"]


@then(parsers.parse("la petición se rechaza con el código {status:d}"))
def rejected_with(context, status):
    assert context["response"].status_code == status
