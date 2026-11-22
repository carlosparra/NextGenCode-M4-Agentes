"""Step definitions for features/hr_assistant.feature."""

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from conftest import ScriptedModel, tool_call

scenarios("features/hr_assistant.feature")


@pytest.fixture(name="world")
def world_fixture():
    """Bolsa mutable que lleva la configuración y la última respuesta.

    :return: Diccionario del escenario.
    :rtype: dict
    """
    return {"model": None, "max_steps": 3, "max_chars": 2000, "response": None}


@given("a model that always asks for a tool")
def _looping_model(world):
    world["model"] = ScriptedModel(
        [tool_call("get_employee", employee_id="EMP-0001")]
    )


@given(parsers.parse("the step limit is {steps:d}"))
def _step_limit(world, steps):
    world["max_steps"] = steps


@given(parsers.parse("the question limit is {chars:d} characters"))
def _question_limit(world, chars):
    world["max_chars"] = chars


@when(parsers.re(r'I ask "(?P<question>.*)"'))
def _ask(world, make_client, question):
    client = make_client(
        model=world["model"],
        max_steps=world["max_steps"],
        max_chars=world["max_chars"],
    )
    world["response"] = client.post("/ask", json={"question": question})


@when("I request the health endpoint")
def _health(world, make_client):
    world["response"] = make_client().get("/health")


@then(parsers.parse("the response status is {status:d}"))
def _status(world, status):
    assert world["response"].status_code == status


@then(parsers.parse('the answer starts with "{prefix}"'))
def _answer_prefix(world, prefix):
    assert world["response"].json()["answer"].startswith(prefix)


@then(parsers.parse('the answer mentions "{text}"'))
def _answer_mentions(world, text):
    assert text in world["response"].json()["answer"]


@then(parsers.parse('the answer does not mention "{text}"'))
def _answer_omits(world, text):
    assert text not in world["response"].json()["answer"]


@then(parsers.parse('the answer is "{text}"'))
def _answer_is(world, text):
    assert world["response"].json()["answer"] == text


@then(parsers.parse('the tools used are "{name}"'))
def _tools_used(world, name):
    assert world["response"].json()["tools_used"] == [name]


@then("no tools were used")
def _no_tools(world):
    assert world["response"].json()["tools_used"] == []


@then(parsers.parse('the health status is "{status}"'))
def _health_status(world, status):
    assert world["response"].json()["status"] == status


@then("the health pid is a number")
def _health_pid(world):
    assert isinstance(world["response"].json()["pid"], int)
