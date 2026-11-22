"""Unit tests for app.tracing with a simulated langsmith."""

import pytest

from app import tracing


def sample(question):
    """Función que se va a trazar.

    :param question: Pregunta de ejemplo.
    :type question: str
    :return: La misma pregunta.
    :rtype: str
    """
    return question


@pytest.mark.parametrize("enabled, api_key", [
    (False, "key"),
    (True, None),
    (True, ""),
])
def test_tracing_off_returns_the_same_function(monkeypatch, enabled, api_key):
    def explode(*_args, **_kwargs):
        raise AssertionError("langsmith must not be used")

    monkeypatch.setattr(tracing, "traceable", explode)
    result = tracing.traced(
        sample, "sample", enabled=enabled, api_key=api_key,
        hide_inputs=True, hide_outputs=True,
    )
    assert result is sample


def test_tracing_on_hides_inputs_and_outputs_when_asked(monkeypatch):
    captured = {}

    def fake_traceable(*_args, **kwargs):
        captured.update(kwargs)
        return lambda func: func

    monkeypatch.setattr(tracing, "traceable", fake_traceable)
    tracing.traced(
        sample, "sample", enabled=True, api_key="key",
        hide_inputs=True, hide_outputs=True,
    )
    assert captured["process_inputs"]({"question": "private"}) == {}
    assert captured["process_outputs"]({"answer": "private"}) == {}
