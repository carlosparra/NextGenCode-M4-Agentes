"""Pruebas de la API y del agente con las palancas de costo."""

import io
import json

import pytest
from fastapi.testclient import TestClient

from app.agent import Agent
from app.llm import ModelReply
from app.main import create_app

SMALL_MODEL = "@cf/meta/llama-3.1-8b-instruct-fast"
SMALL_PRICE = {"input": 0.045, "output": 0.384}
FAKE_TOKEN = "secret-token-xyz"
HISTORY = [
    {"role": "user", "content": "¿Quién es EMP-0004?"},
    {"role": "assistant", "content": "Es una persona de Ventas."},
]


class HalfCachedModel:
    """Modelo cuya primera llamada viene de la caché y la segunda no."""

    def __init__(self):
        self._replies = [
            ModelReply(
                text='{"tool": "get_employee", "args": {"employee_id": "EMP-0004"}}',
                input_tokens=10,
                output_tokens=2,
                cached=True,
            ),
            ModelReply(text='{"answer": "Listo"}', input_tokens=10, output_tokens=2),
        ]

    def complete(self, messages):
        """Devuelve la siguiente respuesta del guion.

        :param messages: Conversación recibida
        :type messages: list[dict]
        :return: Respuesta guionada
        :rtype: ModelReply
        """
        del messages
        return self._replies.pop(0)


def test_history_window_of_zero_sends_no_history(make_observed, scripted_model):
    model = scripted_model(['{"answer": "Hola"}'])
    app = make_observed({"HISTORY_WINDOW": "0"}, model=model)

    response = app.client.post(
        "/ask", json={"question": "¿Y su departamento?", "history": HISTORY}
    )

    assert response.status_code == 200
    assert [message["role"] for message in model.calls[0]] == ["system", "user"]


def test_only_uncached_calls_are_charged(make_observed):
    app = make_observed(model=HalfCachedModel())

    body = app.client.post("/ask", json={"question": "¿Quién es EMP-0004?"}).json()

    expected = (10 * SMALL_PRICE["input"] + 2 * SMALL_PRICE["output"]) / 1_000_000
    assert body["model"] == SMALL_MODEL
    assert body["cached_calls"] == 1
    assert body["input_tokens"] == 20
    assert body["cost_usd"] == pytest.approx(expected)


def test_agent_accepts_json_inside_a_code_block(directory, scripted_model):
    model = scripted_model(['Claro:\n```json\n{"answer": "Hola, soy RR. HH."}\n```'])
    agent = Agent(model, directory, max_steps=3)

    result = agent.run("Hola", [])

    assert result.answer == "Hola, soy RR. HH."
    assert result.stopped == "answer"


def test_agent_run_log_has_model_and_cost_but_no_question_or_token(
    make_gateway_models, gateway_environ, gateway_reply, api_key
):
    question = "¿Quién es EMP-0004?"
    settings, employees, models = make_gateway_models(
        gateway_environ, lambda request: gateway_reply('{"answer": "Hola"}')
    )
    stream = io.StringIO()
    app = create_app(
        settings=settings, directory=employees, log_stream=stream, models=models
    )

    client = TestClient(app, headers={"X-API-Key": api_key})
    client.post("/ask", json={"question": question})

    log = stream.getvalue()
    events = [json.loads(line) for line in log.splitlines() if line.strip()]
    agent_run = next(event for event in events if event["event"] == "agent_run")
    assert agent_run["model"] == SMALL_MODEL
    assert agent_run["cost_usd"] > 0
    assert question not in log
    assert FAKE_TOKEN not in log
    assert FAKE_TOKEN not in repr(settings)
