"""Unit tests for the output formats the real model produces.

Cover fenced JSON, text around the object, dict outputs, the rules that must
not change and the ``invalid_model_output`` event.
"""

import json

import httpx
import pytest

from conftest import (
    GATEWAY_ENV, RecordingLogger, ScriptedModel, answer_json, gateway_reply,
    tool_call,
)

from app.agent import FAILURE_MESSAGE, Agent
from app.config import load_settings
from app.llm import Completion, GatewayModel

MESSAGES = [{"role": "user", "content": "hello"}]


class DictModel:
    """Modelo simulado cuya salida ya es un objeto y no un texto.

    :param replies: Salidas que se devuelven en orden (la última se repite).
    :type replies: list
    """

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def generate(self, messages):
        """Devuelve la siguiente salida dentro de una ``Completion``.

        :param messages: Mensajes que recibe el modelo.
        :type messages: list
        :return: La salida con tokens fijos.
        :rtype: app.llm.Completion
        """
        self.calls.append([dict(message) for message in messages])
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return Completion(text=reply, input_tokens=1, output_tokens=1)


def build(directory, model, max_steps=3):
    logger = RecordingLogger()
    agent = Agent(model=model, directory=directory, max_steps=max_steps,
                  logger=logger)
    return agent, logger


def fenced(text, language="json"):
    """Envuelve ``text`` en una valla de Markdown."""
    return f"```{language}\n{text}\n```"


@pytest.mark.parametrize("language", ["json", ""])
def test_fenced_answer_is_accepted(directory, language):
    model = ScriptedModel([fenced(answer_json("Hi"), language)])
    agent, _ = build(directory, model)
    result = agent.run("Hello?")
    assert result.answer == "Hi"
    assert result.steps == 1


@pytest.mark.parametrize("language", ["json", ""])
def test_fenced_tool_call_is_executed(directory, language):
    call = tool_call("get_employee", employee_id="EMP-0004")
    model = ScriptedModel([fenced(call, language), answer_json("Done")])
    agent, _ = build(directory, model)
    result = agent.run("Who is EMP-0004?")
    assert result.tools_used == ["get_employee"]
    assert result.answer == "Done"


@pytest.mark.parametrize("reply", [
    'Claro: {"answer": "Hi"}',
    '{"answer": "Hi"} Espero que ayude',
    'Claro: {"answer": "Hi"} Espero que ayude',
])
def test_text_around_the_object_is_ignored(directory, reply):
    agent, _ = build(directory, ScriptedModel([reply]))
    assert agent.run("Hello?").answer == "Hi"


def test_the_first_complete_object_is_taken(directory):
    reply = '{"answer": "first"} y luego {"answer": "second"}'
    agent, _ = build(directory, ScriptedModel([reply]))
    assert agent.run("Hello?").answer == "first"


def test_nested_braces_do_not_cut_the_object(directory):
    call = tool_call("get_employee", employee_id="EMP-0001")
    model = ScriptedModel([f"Voy a buscar: {call} ok", answer_json("Done")])
    agent, _ = build(directory, model)
    assert agent.run("Who?").tools_used == ["get_employee"]


def test_a_dict_output_is_accepted_as_an_answer(directory):
    agent, _ = build(directory, DictModel([{"answer": "Hi"}]))
    assert agent.run("Hello?").answer == "Hi"


def test_a_dict_output_can_request_a_tool(directory):
    model = DictModel([
        {"tool": "search_by_department", "args": {"department": "Ventas"}},
        {"answer": "Done"},
    ])
    agent, _ = build(directory, model)
    result = agent.run("Who is in Ventas?")
    assert result.tools_used == ["search_by_department"]
    assert "EMP-0002" in model.calls[1][-1]["content"]


def test_a_dict_with_tool_and_answer_is_still_invalid(directory):
    model = DictModel([{"tool": "get_employee", "answer": "x"}])
    agent, _ = build(directory, model, max_steps=2)
    result = agent.run("Hello?")
    assert result.answer == FAILURE_MESSAGE
    assert result.steps == 2


@pytest.mark.parametrize("reply", [
    "just words, no json",
    "[1, 2, 3]",
    '"a string"',
    '{"tool": "get_employee", "answer": "x"}',
])
def test_invalid_output_still_counts_as_a_step_and_is_bounded(directory, reply):
    model = ScriptedModel([reply])
    agent, _ = build(directory, model, max_steps=3)
    result = agent.run("Hello?")
    assert result.answer == FAILURE_MESSAGE
    assert result.steps == 3
    assert len(model.calls) == 3


def test_a_tool_with_invalid_arguments_still_returns_an_error(directory):
    model = ScriptedModel([
        tool_call("get_employee", wrong="x"), answer_json("Done"),
    ])
    agent, _ = build(directory, model)
    result = agent.run("Who?")
    assert not result.tools_used
    assert model.calls[1][-1]["content"].startswith(
        "Resultado de la herramienta: Error"
    )


@pytest.mark.parametrize("reply, reason", [
    ("just words, no json", "not_json"),
    ("[1, 2, 3]", "not_object"),
    ('{"tool": "get_employee", "answer": "x"}', "bad_shape"),
])
def test_invalid_output_event_has_a_short_reason(directory, reply, reason):
    agent, logger = build(directory, ScriptedModel([reply]), max_steps=2)
    agent.run("Hello?")
    events = logger.named("invalid_model_output")
    assert len(events) == 2
    assert events[0]["reason"] == reason
    assert events[0]["raw_type"] == "str"
    assert events[0]["raw_chars"] == len(reply)


def test_invalid_dict_output_reports_its_type(directory):
    model = DictModel([{"answer": 5}])
    agent, logger = build(directory, model, max_steps=1)
    agent.run("Hello?")
    event = logger.named("invalid_model_output")[0]
    assert event["reason"] == "bad_shape"
    assert event["raw_type"] == "dict"
    assert isinstance(event["raw_chars"], int)


def test_invalid_output_event_never_contains_the_content(directory):
    secret = "salary-of-the-ceo"
    agent, logger = build(
        directory, ScriptedModel([f"no json here: {secret}"]), max_steps=1
    )
    agent.run("Hello?")
    assert logger.named("invalid_model_output")
    assert secret not in repr(logger.events)


def test_valid_output_emits_no_invalid_event(directory):
    agent, logger = build(directory, ScriptedModel([fenced(answer_json("Hi"))]))
    agent.run("Hello?")
    assert logger.named("invalid_model_output") == []


def _gateway(text):
    env = {**GATEWAY_ENV}
    client = httpx.Client(transport=httpx.MockTransport(
        lambda request: gateway_reply(text)
    ))
    return GatewayModel("small-model", load_settings(env), client=client)


def test_gateway_content_as_dict_becomes_serialized_json():
    content = {"answer": "Información útil"}
    completion = _gateway(content).generate(MESSAGES)
    assert completion.text == json.dumps(content, ensure_ascii=False)
    assert isinstance(completion.text, str)


def test_gateway_content_as_str_is_unchanged():
    assert _gateway('{"answer": "ok"}').generate(MESSAGES).text == (
        '{"answer": "ok"}'
    )
