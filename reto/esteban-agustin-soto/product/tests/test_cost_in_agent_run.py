"""Pruebas del campo ``cost_usd`` en el evento ``agent_run`` (sesión 6).

Todo con modelos simulados y sin red. Los precios vienen de la fixture
``prices_path``: ``small-model`` cuesta 1.0 USD por millón de tokens de entrada
y 2.0 de salida.
"""

import httpx
import pytest

from conftest import (
    RecordingLogger, ScriptedModel, answer_json, log_lines, tool_call,
)

from app.agent import Agent
from app.llm import Completion

ASK_KEYS = {
    "model", "route", "cached_calls", "cost_usd", "answer", "steps",
    "tools_used", "input_tokens", "output_tokens", "request_id",
}
METRICS_KEYS = {
    "pid", "requests", "error_rate", "latency_ms", "tokens", "cost_usd", "slo",
}
MILLION = 1_000_000
QUESTION = {"question": "Who is EMP-0004?"}


class CompletionModel:
    """Modelo simulado que devuelve ``Completion`` con tokens y caché fijos.

    :param completions: Respuestas en orden; la última se repite.
    :type completions: list
    """

    def __init__(self, completions):
        self._completions = list(completions)

    def generate(self, messages):
        """Devuelve la siguiente ``Completion`` del guion.

        :param messages: Mensajes que recibe el modelo (no se usan).
        :type messages: list
        :return: La respuesta con su uso.
        :rtype: app.llm.Completion
        """
        del messages
        if len(self._completions) > 1:
            return self._completions.pop(0)
        return self._completions[0]


def _lookup_then_answer(first_cached, second_cached):
    """Arma un modelo de dos llamadas: pide una herramienta y responde.

    :param first_cached: Si la primera llamada vino de la caché.
    :type first_cached: bool
    :param second_cached: Si la segunda llamada vino de la caché.
    :type second_cached: bool
    :return: Modelo con 1 millón de tokens de entrada por llamada y 500 mil
        de salida en la segunda.
    :rtype: CompletionModel
    """
    return CompletionModel([
        Completion(tool_call("get_employee", employee_id="EMP-0004"),
                   MILLION, 0, first_cached),
        Completion(answer_json("Jorge Diaz"), MILLION, MILLION // 2,
                   second_cached),
    ])


@pytest.fixture(name="client_for")
def client_for_fixture(make_costs_client):
    """Fábrica de ``(client, stream)`` con un modelo propio para ambos roles.

    :param make_costs_client: Fábrica de clientes con precios de las pruebas.
    :type make_costs_client: collections.abc.Callable
    :return: Función ``(model) -> (client, stream)``.
    :rtype: collections.abc.Callable
    """

    def build(model):
        return make_costs_client(
            models={"small-model": model, "large-model": model}
        )

    return build


def _agent_runs(stream):
    """Devuelve los eventos ``agent_run`` de la bitácora capturada.

    :param stream: Flujo con la bitácora JSON.
    :type stream: io.StringIO
    :return: Los eventos ``agent_run``.
    :rtype: list
    """
    return [line for line in log_lines(stream) if line["event"] == "agent_run"]


def test_agent_run_cost_equals_the_cost_in_the_ask_response(make_costs_client):
    client, stream = make_costs_client()
    body = client.post("/ask", json=QUESTION).json()
    runs = _agent_runs(stream)
    assert len(runs) == 1
    assert body["cost_usd"] > 0
    assert runs[0]["cost_usd"] == body["cost_usd"]


def test_agent_run_cost_is_a_number_not_text(make_costs_client):
    client, stream = make_costs_client()
    client.post("/ask", json=QUESTION)
    cost = _agent_runs(stream)[0]["cost_usd"]
    assert isinstance(cost, (int, float))
    assert not isinstance(cost, bool)


def test_cached_calls_cost_zero_in_agent_run(client_for):
    client, stream = client_for(_lookup_then_answer(True, True))
    body = client.post("/ask", json=QUESTION).json()
    assert body["cached_calls"] == 2
    assert _agent_runs(stream)[0]["cost_usd"] == 0
    assert body["cost_usd"] == 0


def test_only_the_uncached_call_is_summed(client_for):
    client, stream = client_for(_lookup_then_answer(True, False))
    body = client.post("/ask", json=QUESTION).json()
    # La llamada no cacheada: 1 M de entrada a 1.0 más 0.5 M de salida a 2.0.
    assert _agent_runs(stream)[0]["cost_usd"] == pytest.approx(2.0)
    assert body["cost_usd"] == pytest.approx(2.0)


def test_model_without_a_price_still_fails_and_emits_no_agent_run(
    make_costs_client,
):
    client, stream = make_costs_client(
        env={"MODEL_SMALL": "ghost-small", "MODEL_LARGE": "ghost-large"}
    )
    response = client.post("/ask", json=QUESTION)
    assert response.status_code == 500
    assert _agent_runs(stream) == []
    assert any(line["event"] == "error" for line in log_lines(stream))


def test_agent_run_has_no_cost_without_a_cost_function(directory):
    logger = RecordingLogger()
    agent = Agent(
        model=ScriptedModel([answer_json("Hi")]), directory=directory,
        max_steps=3, logger=logger,
    )
    agent.run("Hello")
    assert "cost_usd" not in logger.named("agent_run")[0]


def test_cost_function_is_called_once_with_the_calls_of_the_run(directory):
    received = []

    def spy(calls):
        received.append(list(calls))
        return 0.25

    logger = RecordingLogger()
    agent = Agent(
        model=ScriptedModel([
            tool_call("get_employee", employee_id="EMP-0004"),
            answer_json("Done"),
        ]),
        directory=directory, max_steps=3, logger=logger, cost_fn=spy,
    )
    agent.run("Who is EMP-0004?")
    assert len(received) == 1
    assert len(received[0]) == 2
    assert logger.named("agent_run")[0]["cost_usd"] == 0.25


def test_ask_response_keeps_exactly_its_ten_keys(make_costs_client):
    client, _ = make_costs_client()
    body = client.post("/ask", json=QUESTION).json()
    assert set(body) == ASK_KEYS


def test_metrics_keeps_its_keys_and_adds_up_the_cost_of_ask(make_costs_client):
    client, _ = make_costs_client()
    costs = [client.post("/ask", json=QUESTION).json()["cost_usd"]
             for _ in range(2)]
    metrics = client.get("/metrics").json()
    assert set(metrics) == METRICS_KEYS
    assert metrics["cost_usd"] == pytest.approx(sum(costs))


def test_unavailable_model_keeps_its_502_with_detail_and_request_id(
    make_costs_client,
):
    def failing(request):
        return httpx.Response(500, request=request, text="boom")

    client, _ = make_costs_client(handler=failing)
    response = client.post(
        "/ask", json=QUESTION, headers={"X-Request-ID": "req-6"}
    )
    assert response.status_code == 502
    assert response.json() == {
        "detail": "model unavailable", "request_id": "req-6",
    }
