"""Pruebas del bucle del agente con modelos dobles."""

import json

from conftest import CAP_MESSAGE, TOOL_RESULT_PREFIX, ScriptedLLM

from app.agent import Agent

ASK_FOR_JORGE = json.dumps(
    {"tool": "get_employee", "args": {"employee_id": "EMP-0004"}}
)
FINAL_ANSWER = json.dumps({"answer": "Listo"})


def make_agent(llm, directory, max_steps=3):
    """Construye un agente con el modelo y el directorio dados."""
    return Agent(llm=llm, directory=directory, max_steps=max_steps)


def test_tool_result_is_sent_back_to_the_model_and_tokens_are_summed(directory):
    llm = ScriptedLLM([ASK_FOR_JORGE, FINAL_ANSWER], input_tokens=10, output_tokens=2)

    result = make_agent(llm, directory).run("¿Quién es EMP-0004?", [])

    assert result.answer == "Listo"
    assert result.steps == 2
    assert result.tools_used == ["get_employee"]
    assert (result.input_tokens, result.output_tokens) == (20, 4)
    tool_message = llm.calls[1][-1]
    assert tool_message["role"] == "user"
    assert tool_message["content"].startswith(TOOL_RESULT_PREFIX)
    assert "Jorge Díaz" in tool_message["content"]


def test_invalid_model_output_does_not_break_the_loop(directory):
    llm = ScriptedLLM(["this is not json"])

    result = make_agent(llm, directory, max_steps=2).run("Hola", [])

    assert result.answer == CAP_MESSAGE
    assert result.steps == 2
    assert llm.calls[1][-1]["content"].startswith(TOOL_RESULT_PREFIX)


def test_unknown_tool_is_reported_to_the_model(directory):
    unknown = json.dumps({"tool": "delete_employee", "args": {}})
    llm = ScriptedLLM([unknown, FINAL_ANSWER])

    result = make_agent(llm, directory).run("Borra a EMP-0004", [])

    assert result.answer == "Listo"
    assert result.tools_used == []
    assert llm.calls[1][-1]["content"].startswith(TOOL_RESULT_PREFIX)


def test_agent_reports_why_it_stopped(directory):
    answered = make_agent(ScriptedLLM([FINAL_ANSWER]), directory).run("Hola", [])
    capped = make_agent(ScriptedLLM([ASK_FOR_JORGE]), directory, max_steps=2).run(
        "¿Quién es EMP-0004?", []
    )

    assert answered.stopped == "answer"
    assert capped.stopped == "max_steps"


def test_history_is_sent_to_the_model_before_the_question(directory):
    history = [
        {"role": "user", "content": "¿Quién es EMP-0001?"},
        {"role": "assistant", "content": "Ana López"},
    ]
    llm = ScriptedLLM([FINAL_ANSWER])

    make_agent(llm, directory).run("¿Y su departamento?", history)

    messages = llm.calls[0]
    assert messages[-3:-1] == history
    assert messages[-1] == {"role": "user", "content": "¿Y su departamento?"}
