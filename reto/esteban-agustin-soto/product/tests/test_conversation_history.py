"""Pruebas de la conversación que el agente le muestra al modelo en cada vuelta.

Defecto en producción: la petición de herramienta del propio modelo no se
agregaba a ``messages``, así que el modelo la repetía sin cerrar con ``answer``.
"""

import json

import pytest

from conftest import (
    RecordingLogger, ScriptedModel, answer_json, field, tool_call,
)

from test_model_output_formats import DictModel

from app.agent import FAILURE_MESSAGE, SYSTEM_PROMPT, Agent
from app.llm import TOOL_RESULT_PREFIX, FakeModel

EMPLOYEE_ID = "EMP-0004"



def build(directory, model, max_steps=3, **options):
    """Crea un agente con el modelo de prueba y opciones extra.

    :param directory: Directorio de empleados.
    :type directory: app.directory.EmployeeDirectory
    :param model: Modelo de prueba.
    :type model: object
    :param max_steps: Tope de vueltas.
    :type max_steps: int
    :param options: Opciones extra del agente (logger, ventana).
    :type options: dict
    :return: El agente.
    :rtype: app.agent.Agent
    """
    return Agent(
        model=model, directory=directory, max_steps=max_steps, **options
    )


def roles(messages):
    """Lista los roles de una conversación.

    :param messages: Mensajes enviados al modelo.
    :type messages: list
    :return: Un rol por mensaje.
    :rtype: list
    """
    return [message["role"] for message in messages]


def tool_instruction(content, expected_json):
    """Extrae lo que sigue al JSON en el mensaje con el resultado.

    :param content: Contenido del mensaje user con el resultado.
    :type content: str
    :param expected_json: JSON del resultado esperado.
    :type expected_json: str
    :return: La instrucción final.
    :rtype: str
    """
    assert content.startswith(TOOL_RESULT_PREFIX + expected_json)
    return content[len(TOOL_RESULT_PREFIX + expected_json):]


def test_model_sees_its_own_tool_request_in_the_next_turn(directory):
    request = tool_call("get_employee", employee_id=EMPLOYEE_ID)
    model = ScriptedModel([request, answer_json("Done")])
    build(directory, model).run("Who is EMP-0004?")
    second = model.calls[1]
    assert roles(second) == ["system", "user", "assistant", "user"]
    assert second[0]["content"] == SYSTEM_PROMPT
    assert second[1]["content"] == "Who is EMP-0004?"
    assert second[2]["content"] == request


def test_a_dict_output_is_appended_as_its_json_text(directory):
    reply = {"tool": "get_employee", "args": {"employee_id": EMPLOYEE_ID}}
    model = DictModel([reply, {"answer": "Listo"}])
    build(directory, model).run("¿Quién es EMP-0004?")
    appended = model.calls[1][2]
    assert appended["role"] == "assistant"
    assert appended["content"] == json.dumps(reply, ensure_ascii=False)


def test_a_dict_output_keeps_non_ascii_characters(directory):
    reply = {"tool": "search_by_department", "args": {"department": "Tecnología"}}
    model = DictModel([reply, {"answer": "Listo"}])
    build(directory, model).run("¿Quién está en Tecnología?")
    appended = model.calls[1][2]
    assert appended["role"] == "assistant"
    assert "Tecnología" in appended["content"]
    assert "\\u" not in appended["content"]


def test_tool_result_message_ends_with_a_short_answer_instruction(directory):
    model = ScriptedModel([
        tool_call("get_employee", employee_id=EMPLOYEE_ID), answer_json("ok"),
    ])
    build(directory, model).run("Who?")
    last = model.calls[1][-1]
    assert last["role"] == "user"
    employee = directory.get_employee(EMPLOYEE_ID)
    expected_json = json.dumps(employee, ensure_ascii=False)
    instruction = tool_instruction(last["content"], expected_json)
    assert "answer" in instruction
    assert 0 < len(instruction.strip()) <= 200


def test_the_answer_instruction_is_the_same_for_every_tool_result(directory):
    model = ScriptedModel([
        tool_call("get_employee", employee_id="EMP-0001"),
        tool_call("get_employee", employee_id="EMP-0002"),
        answer_json("ok"),
    ])
    build(directory, model).run("Who?")
    tails = []
    for call, employee_id in ((1, "EMP-0001"), (2, "EMP-0002")):
        expected = json.dumps(
            directory.get_employee(employee_id), ensure_ascii=False
        )
        tails.append(tool_instruction(model.calls[call][-1]["content"], expected))
    assert tails[0] == tails[1]


def test_every_loop_turn_adds_an_assistant_and_a_user_message(directory):
    first = tool_call("get_employee", employee_id="EMP-0001")
    second = tool_call("search_by_department", department="Ventas")
    model = ScriptedModel([first, second, answer_json("ok")])
    result = build(directory, model, max_steps=3).run("Who?")
    assert field(result, "answer") == "ok"
    third = model.calls[2]
    assert roles(third) == [
        "system", "user", "assistant", "user", "assistant", "user",
    ]
    assert [third[2]["content"], third[4]["content"]] == [first, second]


def test_an_invalid_tool_is_shown_back_with_its_error(directory):
    request = tool_call("get_employee", wrong="x")
    model = ScriptedModel([request, answer_json("Done")])
    build(directory, model).run("Who?")
    second = model.calls[1]
    assert roles(second) == ["system", "user", "assistant", "user"]
    assert second[2]["content"] == request
    assert second[3]["content"].startswith(TOOL_RESULT_PREFIX + "Error")


@pytest.mark.parametrize("reply", [
    "this is not json",
    "[1, 2, 3]",
    '{"tool": "get_employee", "answer": "x"}',
])
def test_an_invalid_output_is_shown_back_as_assistant_text(directory, reply):
    model = ScriptedModel([reply, answer_json("Done")])
    build(directory, model).run("Hello?")
    second = model.calls[1]
    assert roles(second) == ["system", "user", "assistant", "user"]
    assert second[2]["content"] == reply
    assert "inválid" in second[3]["content"]


def test_an_invalid_dict_output_is_appended_as_json_text(directory):
    reply = {"tool": "get_employee", "answer": "x"}
    model = DictModel([reply, {"answer": "Done"}])
    build(directory, model).run("Hello?")
    assert model.calls[1][2] == {
        "role": "assistant",
        "content": json.dumps(reply, ensure_ascii=False),
    }


def test_history_window_trims_only_the_previous_history(directory):
    history = [
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "recent question"},
        {"role": "assistant", "content": "recent answer"},
    ]
    first = tool_call("get_employee", employee_id="EMP-0001")
    second = tool_call("get_employee", employee_id="EMP-0002")
    model = ScriptedModel([first, second, answer_json("ok")])
    agent = build(directory, model, history_window=2)
    agent.run("Now?", history)
    contents = [message["content"] for message in model.calls[2]]
    assert "old question" not in contents
    assert contents[1:4] == ["recent question", "recent answer", "Now?"]
    assert roles(model.calls[2])[4:] == [
        "assistant", "user", "assistant", "user",
    ]


def test_the_step_limit_and_invalid_events_do_not_change(directory):
    logger = RecordingLogger()
    model = ScriptedModel(["not json at all"])
    agent = build(directory, model, max_steps=2, logger=logger)
    result = agent.run("Hello?")
    assert field(result, "answer") == FAILURE_MESSAGE
    assert field(result, "steps") == 2
    assert len(model.calls) == 2
    reasons = [e["reason"] for e in logger.named("invalid_model_output")]
    assert reasons == ["not_json", "not_json"]


def test_invalid_tool_events_are_still_emitted_once_per_turn(directory):
    logger = RecordingLogger()
    model = ScriptedModel([tool_call("nope", x="y")])
    result = build(directory, model, max_steps=3, logger=logger).run("Who?")
    assert field(result, "steps") == 3
    assert len(model.calls) == 3
    events = logger.named("invalid_tool_call")
    assert [e["tool"] for e in events] == ["unknown"] * 3


def test_the_fake_model_resolves_a_tool_question_end_to_end(directory):
    agent = build(directory, FakeModel(directory.departments()))
    result = agent.run("¿Quién es EMP-0004?")
    assert field(result, "tools_used") == ["get_employee"]
    assert field(result, "steps") == 2
    assert "Jorge Diaz" in field(result, "answer")
    assert EMPLOYEE_ID in field(result, "answer")


def test_the_fake_model_still_answers_without_a_tool(directory):
    agent = build(directory, FakeModel(directory.departments()))
    result = agent.run("Hola")
    assert field(result, "steps") == 1
    assert field(result, "tools_used") == []
    assert field(result, "answer")


def test_the_api_answers_a_tool_question_with_the_fake_model(make_client):
    response = make_client().post("/ask", json={"question": "¿Quién es EMP-0004?"})
    assert response.status_code == 200
    body = response.json()
    assert body["tools_used"] == ["get_employee"]
    assert "Jorge Diaz" in body["answer"]
