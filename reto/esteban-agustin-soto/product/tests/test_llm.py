"""Unit tests for the fake model in app.llm."""

import json

import pytest

from app.llm import FakeModel


@pytest.fixture(name="model")
def model_fixture():
    return FakeModel(["Tecnología", "Ventas", "Finanzas"])


def ask(model, text):
    return json.loads(model.complete([{"role": "user", "content": text}]))


def test_tool_result_is_turned_into_an_answer(model):
    reply = ask(model, "Resultado de la herramienta: Jorge Diaz")
    assert reply == {"answer": "Según el directorio: Jorge Diaz"}


def test_employee_id_wins_over_department(model):
    reply = ask(model, "Is EMP-0002 in Tecnología?")
    assert reply["tool"] == "get_employee"
    assert reply["args"]["employee_id"] == "EMP-0002"


def test_department_and_help_rules(model):
    assert ask(model, "Who is in Ventas?")["tool"] == "search_by_department"
    help_reply = ask(model, "Hello")
    assert help_reply["answer"].startswith("Pregúntame por un empleado")
