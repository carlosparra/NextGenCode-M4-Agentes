"""Pruebas del modelo simulado (MODEL_PROVIDER=fake)."""

import json

from conftest import TOOL_RESULT_PREFIX


def user(content):
    """Arma un mensaje de usuario."""
    return {"role": "user", "content": content}


def test_tool_result_is_answered_even_if_it_contains_an_employee_id(fake_llm):
    result = '{"id": "EMP-0004", "name": "Jorge Díaz"}'

    completion = fake_llm.complete([user(TOOL_RESULT_PREFIX + result)])

    assert json.loads(completion.text) == {"answer": f"Según el directorio: {result}"}


def test_employee_id_takes_priority_over_department(fake_llm):
    completion = fake_llm.complete([user("¿EMP-0001 trabaja en Ventas?")])

    assert json.loads(completion.text) == {
        "tool": "get_employee",
        "args": {"employee_id": "EMP-0001"},
    }


def test_tokens_are_counted_as_words(fake_llm):
    messages = [
        {"role": "system", "content": "uno dos"},
        user("hola tres cuatro"),
    ]

    completion = fake_llm.complete(messages)

    assert completion.input_tokens == 5
    assert completion.output_tokens == len(completion.text.split())
