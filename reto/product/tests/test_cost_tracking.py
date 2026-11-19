"""Pruebas del costo por respuesta: ventana, cache, modelos simulados y metricas."""

import threading

import pytest

from conftest import LARGE_MODEL, SMALL_MODEL, ScriptedLLM
from app.agent import Agent
from app.llm import Completion, FakeLLM, build_models
from app.metrics import Metrics
from app.pricing import PriceTable

HISTORY = [
    {"role": "user" if index % 2 == 0 else "assistant", "content": f"m{index}"}
    for index in range(10)
]


class SequenceLLM:  # pylint: disable=too-few-public-methods
    """Modelo doble que devuelve ``Completion`` ya armadas, en orden."""

    def __init__(self, completions):
        self.completions = list(completions)

    def complete(self, messages):
        """Devuelve la siguiente respuesta preparada.

        :param messages: Conversacion enviada por el agente
        :type messages: list[dict]
        :return: La siguiente respuesta
        :rtype: Completion
        """
        assert messages
        return self.completions.pop(0)


@pytest.mark.parametrize("window", [0, 1, 6, 100])
def test_history_window_keeps_only_the_latest_messages(directory, window):
    spy = ScriptedLLM(['{"answer": "ok"}'])
    agent = Agent(spy, directory, 3, history_window=window)

    agent.run("¿Quién es EMP-0004?", HISTORY)

    sent = spy.calls[0]
    expected = HISTORY[-window:] if window else []
    assert sent[0]["role"] == "system"
    assert sent[1:-1] == expected
    assert sent[-1] == {"role": "user", "content": "¿Quién es EMP-0004?"}


def test_cached_calls_are_counted_and_do_not_add_cost(directory, prices_file):
    llm = SequenceLLM(
        [
            Completion(
                text='{"tool": "get_employee", "args": {"employee_id": "EMP-0004"}}',
                input_tokens=1_000_000,
                output_tokens=0,
            ),
            Completion(
                text='{"answer": "Jorge"}',
                input_tokens=1_000_000,
                output_tokens=0,
                cached=True,
            ),
        ]
    )
    agent = Agent(
        llm,
        directory,
        3,
        model=SMALL_MODEL,
        prices=PriceTable.load(prices_file),
    )

    result = agent.run("¿Quién es EMP-0004?", [])

    assert result.model == SMALL_MODEL
    assert result.cached_calls == 1
    assert result.cost_usd == pytest.approx(0.045)


def test_simulated_models_answer_the_same_and_sign_with_their_name(
    make_settings, directory
):
    messages = [{"role": "user", "content": "¿Quién es EMP-0004?"}]
    small = FakeLLM(directory.departments(), model=SMALL_MODEL).complete(messages)
    large = FakeLLM(directory.departments(), model=LARGE_MODEL).complete(messages)

    models = build_models(make_settings(), directory)

    assert small.text == large.text
    assert (small.model, large.model) == (SMALL_MODEL, LARGE_MODEL)
    assert set(models) == {SMALL_MODEL, LARGE_MODEL}


def test_metrics_add_up_the_cost_from_many_threads():
    metrics = Metrics()

    def add_many():
        for _ in range(100):
            metrics.add_cost(0.001)

    threads = [threading.Thread(target=add_many) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert metrics.snapshot(slo_p95_ms=2000)["cost_usd"] == pytest.approx(0.8)
