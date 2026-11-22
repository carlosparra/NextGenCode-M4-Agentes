"""Unit tests for the events the agent emits."""

import pytest

from conftest import RecordingLogger, ScriptedModel, answer_json, tool_call

from app.agent import Agent


def build(directory, replies, max_steps=3):
    logger = RecordingLogger()
    agent = Agent(
        model=ScriptedModel(replies), directory=directory,
        max_steps=max_steps, logger=logger,
    )
    return agent, logger


def test_each_tool_call_is_audited(directory):
    agent, logger = build(directory, [
        tool_call("get_employee", employee_id="EMP-0004"),
        answer_json("Done"),
    ])
    agent.run("Who is EMP-0004?")
    audits = logger.named("audit")
    assert len(audits) == 1
    assert audits[0]["action"] == "tool_call"
    assert audits[0]["tool"] == "get_employee"
    assert audits[0]["args"] == {"employee_id": "EMP-0004"}


@pytest.mark.parametrize("replies, stopped, steps", [
    ([answer_json("Hi")], "answer", 1),
    ([tool_call("get_employee", employee_id="EMP-0001")], "max_steps", 2),
])
def test_agent_run_reports_counts_and_why_it_stopped(
    directory, replies, stopped, steps
):
    agent, logger = build(directory, replies, max_steps=2)
    history = [{"role": "user", "content": "a"},
               {"role": "assistant", "content": "b"}]
    agent.run("Question?", history)
    runs = logger.named("agent_run")
    assert len(runs) == 1
    assert runs[0]["stopped"] == stopped
    assert runs[0]["steps"] == steps
    assert runs[0]["question_chars"] == len("Question?")
    assert runs[0]["history_messages"] == 2
    assert runs[0]["input_tokens"] > 0
    assert runs[0]["output_tokens"] > 0


def test_events_never_contain_the_question_or_the_answer(directory):
    agent, logger = build(directory, [answer_json("classified reply")])
    agent.run("classified question")
    dump = repr(logger.events)
    assert "classified question" not in dump
    assert "classified reply" not in dump
