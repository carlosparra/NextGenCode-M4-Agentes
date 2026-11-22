"""Unit tests for the history window and the cost metric."""

import pytest

from conftest import ScriptedModel, answer_json

from app.agent import Agent
from app.observability import MetricsCollector


def _history(count):
    """Build ``count`` alternating messages numbered from zero."""
    roles = ("user", "assistant")
    return [{"role": roles[i % 2], "content": f"message {i}"}
            for i in range(count)]


def _sent_messages(directory, window, history):
    """Run the agent once and return the messages the model received."""
    model = ScriptedModel([answer_json("done")])
    agent = Agent(model=model, directory=directory, max_steps=3,
                  history_window=window)
    agent.run("question", history)
    return model.calls[0]


def test_only_the_last_window_messages_reach_the_model(directory):
    sent = _sent_messages(directory, 2, _history(10))
    contents = [m["content"] for m in sent]
    assert contents[1:] == ["message 8", "message 9", "question"]


def test_a_window_larger_than_the_history_keeps_everything(directory):
    sent = _sent_messages(directory, 6, _history(3))
    assert len(sent) == 1 + 3 + 1


def test_metrics_accumulate_cost():
    metrics = MetricsCollector(2000)
    assert metrics.snapshot()["cost_usd"] == 0
    metrics.add_cost(0.5)
    metrics.add_cost(0.25)
    assert metrics.snapshot()["cost_usd"] == pytest.approx(0.75)
