"""Unit tests for the system prompt and the ``invalid_tool_call`` event.

The real model invents tool names or arguments when the prompt does not
list the tools, so the prompt must name them and every invalid call must
leave a safe trace in the logs.
"""

import json

import pytest

from conftest import EMPLOYEES, RecordingLogger, ScriptedModel, answer_json, tool_call

from app.agent import FAILURE_MESSAGE, SYSTEM_PROMPT, Agent

SECRET = "SECRET-VALUE-9931"
ERROR_FEEDBACK = "Resultado de la herramienta: Error: herramienta o argumentos inv"


def build(directory, model, max_steps=3):
    """Crea un agente con un logger de prueba.

    :param directory: Directorio de empleados.
    :type directory: app.directory.EmployeeDirectory
    :param model: Modelo simulado.
    :type model: object
    :param max_steps: Tope de vueltas del bucle.
    :type max_steps: int
    :return: El agente y su logger.
    :rtype: tuple
    """
    logger = RecordingLogger()
    agent = Agent(model=model, directory=directory, max_steps=max_steps,
                  logger=logger)
    return agent, logger


@pytest.mark.parametrize("fragment", [
    "get_employee", "employee_id", "search_by_department", "department",
])
def test_prompt_names_each_tool_and_its_argument(fragment):
    assert fragment in SYSTEM_PROMPT


def test_prompt_mentions_the_employee_id_format():
    assert "EMP-0004" in SYSTEM_PROMPT


@pytest.mark.parametrize("example", ['{"tool"', '"args"', '{"answer"'])
def test_prompt_contains_both_response_examples(example):
    assert example in SYSTEM_PROMPT


def test_prompt_is_short_and_fixed_text():
    assert isinstance(SYSTEM_PROMPT, str)
    assert len(SYSTEM_PROMPT) < 1200


def test_prompt_has_no_employee_data_or_secrets():
    lowered = SYSTEM_PROMPT.lower()
    for employee in EMPLOYEES:
        for key in ("name", "role", "start_date"):
            assert employee[key].lower() not in lowered
    for word in ("api_key", "secret", "password", "bearer", "http"):
        assert word not in lowered


@pytest.mark.parametrize("name, args, expected_tool, expected_keys", [
    ("delete_all", {"zeta": "x", "alpha": "y"}, "unknown", ["alpha", "zeta"]),
    ("get_employee", {"id": "EMP-0001"}, "get_employee", ["id"]),
    ("search_by_department", {"dept": "Ventas", "a": 1},
     "search_by_department", ["a", "dept"]),
])
def test_invalid_tool_call_event_reports_tool_and_sorted_keys(
    directory, name, args, expected_tool, expected_keys
):
    agent, logger = build(directory, ScriptedModel([tool_call(name, **args)]),
                          max_steps=1)
    agent.run("Who?")
    events = logger.named("invalid_tool_call")
    assert len(events) == 1
    assert events[0]["tool"] == expected_tool
    assert events[0]["arg_keys"] == expected_keys


def test_invalid_tool_call_without_args_has_no_keys(directory):
    reply = json.dumps({"tool": "get_employee"})
    agent, logger = build(directory, ScriptedModel([reply]), max_steps=1)
    agent.run("Who?")
    assert logger.named("invalid_tool_call")[0]["arg_keys"] == []


def test_invalid_tool_call_never_logs_argument_values(directory):
    reply = tool_call("get_employee", ssn=SECRET)
    agent, logger = build(directory, ScriptedModel([reply]), max_steps=2)
    agent.run(f"Tell me about {SECRET}")
    assert logger.named("invalid_tool_call")
    assert SECRET not in repr(logger.events)


def test_unknown_tool_name_is_not_written_to_the_log(directory):
    reply = tool_call(f"drop_{SECRET}", note="x")
    agent, logger = build(directory, ScriptedModel([reply]), max_steps=1)
    agent.run("Who?")
    assert SECRET not in repr(logger.events)
    assert logger.named("invalid_tool_call")[0]["tool"] == "unknown"


def test_invalid_tool_still_returns_error_feedback_to_the_model(directory):
    model = ScriptedModel([
        tool_call("get_employee", wrong="x"), answer_json("Done"),
    ])
    agent, _ = build(directory, model)
    result = agent.run("Who?")
    assert model.calls[1][-1]["content"].startswith(ERROR_FEEDBACK)
    assert result.answer == "Done"
    assert not result.tools_used


def test_invalid_tool_calls_count_as_steps_and_stay_bounded(directory):
    model = ScriptedModel([tool_call("nope", x="y")])
    agent, logger = build(directory, model, max_steps=3)
    result = agent.run("Who?")
    assert result.answer == FAILURE_MESSAGE
    assert result.steps == 3
    assert len(model.calls) == 3
    assert len(logger.named("invalid_tool_call")) == 3


def test_valid_call_runs_without_an_invalid_tool_event(directory):
    model = ScriptedModel([
        tool_call("get_employee", employee_id="EMP-0004"), answer_json("Done"),
    ])
    agent, logger = build(directory, model)
    result = agent.run("Who is EMP-0004?")
    assert result.tools_used == ["get_employee"]
    assert logger.named("invalid_tool_call") == []
    assert "Jorge Diaz" in model.calls[1][-1]["content"]
