"""Pruebas unitarias del bucle del agente (``app.agent.Agent``)."""

import json

import pytest

from conftest import CAP_MESSAGE, SMALL_MODEL, AlwaysToolModel, ScriptedModel

from app.agent import Agent

PREFIX = "Resultado de la herramienta: "


def _answer(text):
    """Texto JSON de una respuesta final del modelo."""
    return json.dumps({"answer": text})


def _tool(name, args):
    """Texto JSON de una petición de herramienta."""
    return json.dumps({"tool": name, "args": args})


def _run(model, directory, max_steps=3, question="Pregunta", history=None, **kw):
    """Corre el agente con el modelo y el directorio indicados."""
    agent = Agent(model, directory, max_steps, **kw)
    return agent.run(question, history or [])


def test_direct_answer_takes_one_step(directory):
    model = ScriptedModel([(_answer("Hola."), 4, 2)])

    result = _run(model, directory)

    assert result.answer == "Hola."
    assert result.steps == 1
    assert not result.tools_used


def test_tool_result_is_sent_back_to_the_model(directory):
    model = ScriptedModel(
        [
            (_tool("get_employee", {"employee_id": "EMP-0004"}), 3, 2),
            (_answer("Es Jorge Díaz."), 5, 4),
        ]
    )

    result = _run(model, directory)

    last_message = model.calls[1][-1]
    assert last_message["role"] == "user"
    assert last_message["content"].startswith(PREFIX)
    assert "Jorge Díaz" in last_message["content"]
    assert result.steps == 2
    assert result.tools_used == ["get_employee"]


def test_tokens_of_every_step_are_added(directory):
    model = ScriptedModel(
        [
            (_tool("get_employee", {"employee_id": "EMP-0001"}), 3, 2),
            (_answer("Listo."), 5, 4),
        ]
    )

    result = _run(model, directory)

    assert result.input_tokens == 8
    assert result.output_tokens == 6


def test_agent_stops_at_the_step_cap(directory):
    result = _run(AlwaysToolModel(), directory, max_steps=3)

    assert result.answer == CAP_MESSAGE
    assert result.steps == 3


@pytest.mark.parametrize(
    "bad_reply",
    [
        "esto no es JSON",
        _tool("delete_employee", {"employee_id": "EMP-0001"}),
        _tool("get_employee", {}),
    ],
    ids=["invalid_json", "unknown_tool", "missing_arguments"],
)
def test_bad_model_output_is_reported_to_the_model(directory, bad_reply):
    model = ScriptedModel([(bad_reply, 1, 1), (_answer("Perdón."), 1, 1)])

    result = _run(model, directory)

    assert model.calls[1][-1]["content"].startswith(PREFIX)
    assert result.answer == "Perdón."
    assert result.steps == 2


def test_history_window_never_trims_the_tool_loop(directory):
    model = ScriptedModel(
        [
            (_tool("get_employee", {"employee_id": "EMP-0004"}), 1, 1),
            (_answer("Es Jorge Díaz."), 1, 1),
        ]
    )
    history = [{"role": "user", "content": f"Mensaje {n}"} for n in range(5)]

    _run(model, directory, question="¿EMP-0004?", history=history, history_window=2)

    first_call = [message["content"] for message in model.calls[0]]
    second_call = model.calls[1]
    assert first_call == ["Mensaje 3", "Mensaje 4", "¿EMP-0004?"]
    assert len(second_call) == 5
    assert second_call[-1]["content"].startswith(PREFIX)


def test_history_window_of_zero_sends_only_the_question(directory):
    model = ScriptedModel([(_answer("Listo."), 1, 1)])
    history = [{"role": "user", "content": "Mensaje previo"}]

    _run(model, directory, question="Hola", history=history, history_window=0)

    assert model.calls[0] == [{"role": "user", "content": "Hola"}]


def test_cost_of_every_step_is_added_and_cached_calls_are_free(
    directory, prices
):
    model = ScriptedModel(
        [
            (_tool("get_employee", {"employee_id": "EMP-0001"}), 1000, 100, True),
            (_answer("Listo."), 1000, 100, False),
        ],
        name=SMALL_MODEL,
    )

    result = _run(model, directory, prices=prices)

    assert result.model == SMALL_MODEL
    assert result.cached_calls == 1
    assert result.cost_usd == pytest.approx(prices.cost(SMALL_MODEL, 1000, 100))
    assert result.input_tokens == 2000


class RecordingTracer:
    """Tracer de prueba que guarda con qué cliente se envolvió cada función."""

    def __init__(self):
        self.calls = []

    def wrap(self, function, name, run_type, request_id, client=None):
        """Guarda nombre, id y cliente, y devuelve la función sin cambios.

        :param function: Función que se trazaría
        :type function: callable
        :param name: Nombre de la traza
        :type name: str
        :param run_type: Tipo de traza; no se usa
        :type run_type: str
        :param request_id: Id de la petición
        :type request_id: str
        :param client: Nombre del cliente
        :type client: str or None
        :return: La misma función
        :rtype: callable
        """
        del run_type
        self.calls.append((name, request_id, client))
        return function


def test_agent_tags_every_trace_with_the_client(directory):
    tracer = RecordingTracer()
    model = ScriptedModel(
        [
            (_tool("get_employee", {"employee_id": "EMP-0001"}), 1, 1),
            (_answer("Listo."), 1, 1),
        ]
    )

    _run(model, directory, tracer=tracer, request_id="req-1", client="acme")

    assert {name for name, _, _ in tracer.calls} == {
        "agent", "model", "get_employee",
    }
    assert all(call[1:] == ("req-1", "acme") for call in tracer.calls)
