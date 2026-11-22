"""Pruebas unitarias del modelo simulado (``MODEL_PROVIDER=fake``)."""

import json

import pytest

from app.llm import FakeModel

DEPARTMENTS = ["Tecnología", "Ventas", "Finanzas"]


@pytest.fixture
def model():
    """Modelo simulado con los departamentos de los datos.

    :return: Modelo determinista
    :rtype: FakeModel
    """
    return FakeModel(DEPARTMENTS)


def user(content):
    """Arma un mensaje del usuario.

    :param content: Texto del mensaje
    :type content: str
    :return: Mensaje con rol ``user``
    :rtype: dict
    """
    return {"role": "user", "content": content}


def test_fake_model_asks_for_get_employee_when_an_id_is_mentioned(model):
    reply = model.complete([user("¿Quién es EMP-0002?")])

    assert json.loads(reply.text) == {
        "tool": "get_employee",
        "args": {"employee_id": "EMP-0002"},
    }


def test_tool_result_takes_priority_over_an_employee_id(model):
    content = 'Resultado de la herramienta: {"id": "EMP-0002"}'

    reply = model.complete([user("¿Quién es EMP-0002?"), user(content)])

    expected = 'Según el directorio: {"id": "EMP-0002"}'
    assert json.loads(reply.text) == {"answer": expected}


def test_fake_model_counts_words_of_all_messages_as_input_tokens(model):
    messages = [user("Hola equipo"), user("una pregunta corta")]

    reply = model.complete(messages)

    assert reply.input_tokens == 5
    assert reply.output_tokens > 0
