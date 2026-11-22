"""Unit tests for app.agent."""

import pytest

from conftest import ScriptedModel, answer_json, field, tool_call

from app.agent import Agent

FAILURE = "No pude completar la respuesta. Intenta con una pregunta más concreta."


def build(directory, replies, max_steps=3):
    model = ScriptedModel(replies)
    return Agent(model=model, directory=directory, max_steps=max_steps), model


def test_direct_answer_takes_one_step(directory):
    agent, _ = build(directory, [answer_json("Hola")])
    result = agent.run("Hi")
    assert field(result, "answer") == "Hola"
    assert field(result, "steps") == 1
    assert field(result, "tools_used") == []


def test_tool_result_is_fed_back_to_the_model(directory):
    agent, model = build(directory, [
        tool_call("get_employee", employee_id="EMP-0004"),
        answer_json("Es Jorge"),
    ])
    result = agent.run("Who is EMP-0004?")
    assert field(result, "answer") == "Es Jorge"
    assert field(result, "steps") == 2
    assert field(result, "tools_used") == ["get_employee"]
    last = model.calls[1][-1]
    assert last["role"] == "user"
    assert last["content"].startswith("Resultado de la herramienta: ")
    assert "Jorge Diaz" in last["content"]


def test_loop_stops_at_the_step_limit(directory):
    agent, model = build(
        directory, [tool_call("get_employee", employee_id="EMP-0001")],
        max_steps=2,
    )
    result = agent.run("Anything")
    assert field(result, "answer") == FAILURE
    assert len(model.calls) == 2


@pytest.mark.parametrize(
    "bad_reply",
    [
        "this is not json",
        tool_call("fire_everyone"),
        tool_call("get_employee"),
    ],
)
def test_malformed_model_output_never_raises(directory, bad_reply):
    agent, _ = build(directory, [bad_reply])
    assert field(agent.run("Anything"), "answer") == FAILURE


def test_history_is_sent_before_the_question(directory):
    agent, model = build(directory, [answer_json("ok")])
    history = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "reply"},
    ]
    result = agent.run("second", history)
    contents = [m["content"] for m in model.calls[0]]
    assert contents[-3:] == ["first", "reply", "second"]
    assert field(result, "input_tokens") >= 3
    assert field(result, "output_tokens") >= 1
