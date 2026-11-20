"""Pruebas unitarias del bucle del agente.

Verifica que el agente interpreta correctamente las respuestas
del modelo, invoca herramientas, y respeta el tope de pasos.
Desde la sesion 3 el modelo se elige por peticion (``run`` lo
recibe) y el agente suma el costo de cada llamada con la tabla de
precios. Las fixtures ``directory`` y ``prices`` vienen de
``conftest.py``.
"""

import io
import json

import pytest

from app.agent import Agent
from app.llm import Completion, FakeModel
from app.logs import JsonLogger
from tests.conftest import MODEL_SMALL, FakeClock


class TestAgentLoop:
    """Comportamiento del bucle del agente."""

    def test_direct_answer_ends_loop(self, directory, prices):
        """El agente termina cuando el modelo da una respuesta
        directa sin pedir herramientas.
        """
        agent = Agent(directory=directory, prices=prices, max_steps=3)
        # Pregunta generica: el fake devuelve answer directa
        result = agent.run("Hello there", model=FakeModel())
        assert result["answer"] is not None
        assert result["steps"] >= 1

    def test_tool_call_then_answer(self, directory, prices):
        """El agente invoca una herramienta y luego devuelve
        la respuesta basada en el resultado.
        """
        agent = Agent(directory=directory, prices=prices, max_steps=3)
        result = agent.run("Tell me about EMP-0001", model=FakeModel())
        assert "get_employee" in result["tools_used"]
        assert result["steps"] == 2

    def test_step_cap_returns_fallback(self, directory, prices):
        """Al alcanzar el tope de pasos sin respuesta, el agente
        devuelve el mensaje de fallback predefinido.
        """
        agent = Agent(directory=directory, prices=prices, max_steps=1)
        # Pregunta que requiere herramienta: con 1 paso
        # no puede completar el ciclo herramienta + respuesta
        result = agent.run("Who is EMP-0001?", model=FakeModel())
        assert "No pude completar" in result["answer"]
        assert result["steps"] == 1


# -- Sesion 2: eventos del agente en el log ---------------------------

def _logged_agent(directory, prices, max_steps):
    """Crea un agente que escribe su log en un ``StringIO``.

    :param directory: Directorio de empleados de prueba.
    :type directory: app.directory.Directory
    :param prices: Tabla de precios.
    :type prices: app.pricing.PriceTable
    :param max_steps: Tope de pasos del bucle.
    :type max_steps: int
    :return: El agente y el stream de su log.
    :rtype: tuple[app.agent.Agent, io.StringIO]
    """
    stream = io.StringIO()
    logger = JsonLogger(stream=stream, service="hr-assistant", clock=FakeClock())
    agent = Agent(
        directory=directory,
        prices=prices,
        max_steps=max_steps,
        logger=logger,
    )
    return agent, stream


def _events(stream, name):
    """Filtra los eventos del log por nombre.

    :param stream: Log escrito por el agente.
    :type stream: io.StringIO
    :param name: Nombre del evento.
    :type name: str
    :return: Eventos parseados.
    :rtype: list[dict]
    """
    lines = stream.getvalue().splitlines()
    return [e for e in map(json.loads, lines) if e["event"] == name]


def test_agent_logs_audit_and_agent_run_without_any_text(directory, prices):
    """Una herramienta produce un ``audit`` y la corrida un
    ``agent_run`` con conteos, sin el texto de pregunta ni respuesta.
    """
    agent, stream = _logged_agent(directory, prices, max_steps=3)
    question = "Who is EMP-0001?"
    history = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]

    result = agent.run(question, history, model=FakeModel(), request_id="req-agent")

    assert result["stopped"] == "answer"
    (audit,) = _events(stream, "audit")
    assert audit["request_id"] == "req-agent"
    assert audit["action"] == "tool_call"
    assert audit["tool"] == "get_employee"
    assert audit["args"] == {"employee_id": "EMP-0001"}
    (run,) = _events(stream, "agent_run")
    assert run["request_id"] == "req-agent"
    assert run["question_chars"] == len(question)
    assert run["history_messages"] == 2
    assert run["steps"] == 2
    assert run["tools"] == ["get_employee"]
    assert run["input_tokens"] == result["input_tokens"]
    assert run["output_tokens"] == result["output_tokens"]
    assert run["stopped"] == "answer"
    assert "Who is" not in stream.getvalue()
    assert "Ana Lopez" not in stream.getvalue()


def test_agent_reports_max_steps_when_it_stops_at_the_cap(directory, prices):
    """Si el bucle llega al tope, ``stopped`` vale ``max_steps``."""
    agent, stream = _logged_agent(directory, prices, max_steps=1)

    result = agent.run(
        "Who is EMP-0001?", None, model=FakeModel(), request_id="req-cap"
    )

    assert result["stopped"] == "max_steps"
    (run,) = _events(stream, "agent_run")
    assert run["stopped"] == "max_steps"
    assert run["steps"] == 1
    assert run["request_id"] == "req-cap"


# -- Sesion 3: costo por llamada ---------------------------------------

class ScriptedModel:
    """Modelo que devuelve una lista fija de ``Completion``.

    :param name: Nombre del modelo.
    :type name: str
    :param completions: Respuestas en orden, una por llamada.
    :type completions: list[app.llm.Completion]
    """

    def __init__(self, name, completions):
        """Guarda el nombre y las respuestas.

        :param name: Nombre del modelo.
        :type name: str
        :param completions: Respuestas en orden.
        :type completions: list[app.llm.Completion]
        """
        self.name = name
        self._completions = list(completions)

    def complete(self, messages):
        """Devuelve la siguiente respuesta de la lista.

        :param messages: Mensajes de la conversacion (ignorados).
        :type messages: list[dict[str, str]]
        :return: Siguiente respuesta.
        :rtype: app.llm.Completion
        """
        del messages
        return self._completions.pop(0)


def test_agent_adds_the_cost_of_each_call_and_cached_calls_are_free(
    directory, prices
):
    """Una llamada normal cuesta segun su modelo; la llamada que vino
    de la cache cuenta en ``cached_calls`` y cuesta 0. ``agent_run``
    lleva modelo, ruta, llamadas cacheadas y costo, sin texto.
    """
    tool_call = json.dumps(
        {"tool": "get_employee", "args": {"employee_id": "EMP-0001"}}
    )
    answer = json.dumps({"answer": "Ana Lopez trabaja en Tecnologia"})
    model = ScriptedModel(
        MODEL_SMALL,
        [
            Completion(
                text=tool_call, input_tokens=1000, output_tokens=500, cached=False
            ),
            Completion(
                text=answer, input_tokens=2000, output_tokens=100, cached=True
            ),
        ],
    )
    agent, stream = _logged_agent(directory, prices, max_steps=3)

    result = agent.run(
        "Who is EMP-0001?",
        None,
        model=model,
        request_id="req-cost",
        route="keyword",
    )

    # 1000 * 0.045 / 1e6 + 500 * 0.384 / 1e6; la segunda llamada es gratis
    assert result["cost_usd"] == pytest.approx(0.000237)
    assert result["cached_calls"] == 1
    assert result["input_tokens"] == 3000
    assert result["model"] == MODEL_SMALL
    assert result["route"] == "keyword"
    (run,) = _events(stream, "agent_run")
    assert run["model"] == MODEL_SMALL
    assert run["route"] == "keyword"
    assert run["cached_calls"] == 1
    assert run["cost_usd"] == pytest.approx(0.000237)
    assert "Ana Lopez" not in stream.getvalue()


# -- Sesion 4: cliente en log y trazas ----------------------------------

class RecordingTracer:
    """Trazador falso que anota los metadatos de cada traza.

    No envuelve nada: devuelve la funcion tal cual.
    """

    enabled = True

    def __init__(self):
        """Empieza sin trazas anotadas."""
        self.metadata = []

    def traceable(self, name, run_type, metadata=None):
        """Anota los metadatos y devuelve un decorador identidad.

        :param name: Nombre de la traza.
        :type name: str
        :param run_type: Tipo de corrida.
        :type run_type: str
        :param metadata: Metadatos de la traza.
        :type metadata: dict | None
        :return: Decorador que no cambia la funcion.
        :rtype: callable
        """
        del name, run_type
        self.metadata.append(dict(metadata or {}))
        return lambda func: func


def test_agent_names_the_client_in_audit_agent_run_and_traces(directory, prices):
    """``client`` va en cada ``audit``, en ``agent_run`` y en los
    metadatos de todas las trazas.
    """
    stream = io.StringIO()
    tracer = RecordingTracer()
    agent = Agent(
        directory=directory,
        prices=prices,
        max_steps=3,
        logger=JsonLogger(stream=stream, service="hr-assistant", clock=FakeClock()),
        tracer=tracer,
    )

    agent.run(
        "Who is EMP-0001?", model=FakeModel(), request_id="req-c", client="acme"
    )

    (audit,) = _events(stream, "audit")
    (run,) = _events(stream, "agent_run")
    assert audit["client"] == "acme"
    assert run["client"] == "acme"
    assert tracer.metadata
    assert all(meta.get("client") == "acme" for meta in tracer.metadata)
