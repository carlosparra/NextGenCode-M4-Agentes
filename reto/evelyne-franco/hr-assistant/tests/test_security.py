"""Pruebas de la auditoria de seguridad y de su integracion.

Cubre ``app.security.SecurityAudit``, la llave ``security`` de
``app.metrics``, ``MAX_ANSWER_CHARS`` y ``secret_values()`` de
``app.config``, la validacion de argumentos en ``app.agent`` y el campo
``redactions`` y la validacion de la salida en ``POST /ask``.

:seealso: ``spec/05-security-hardening.md``
"""

import io
import json

import pytest
from pydantic import SecretStr

from app.agent import UNKNOWN_TOOL_KIND, Agent
from app.auth import parse_api_keys
from app.config import Settings, load_settings
from app.logs import JsonLogger
from app.main import ASK_FIELDS
from app.metrics import Metrics
from app.security import SecurityAudit
from tests.conftest import (
    LONG_NAME,
    SAFE_FALLBACK_ANSWER,
    SLO_P95_MS,
    UNKNOWN_DEPARTMENT,
    BadArgsModel,
    EmptyAnswerModel,
    FakeClock,
    RecordingTracer,
)

SECURITY_CONTROLS = ("pii", "secret", "output_invalid", "tool_args", "injection")


class FakeAudit:
    """Auditoria en memoria para probar el agente sin log ni metricas."""

    def __init__(self):
        """Inicializa la lista de registros."""
        self.records = []

    # pylint: disable-next=too-many-arguments,too-many-positional-arguments
    def record(self, request_id, client, stage, control, kinds):
        """Anota un evento de seguridad.

        :param request_id: Id de la peticion.
        :type request_id: str
        :param client: Cliente que pregunta.
        :type client: str
        :param stage: ``input`` u ``output``.
        :type stage: str
        :param control: Control que detecto algo.
        :type control: str
        :param kinds: Tipos detectados.
        :type kinds: list[str]
        """
        self.records.append(
            {
                "request_id": request_id,
                "client": client,
                "stage": stage,
                "control": control,
                "kinds": list(kinds),
            }
        )


class SpyDirectory:
    """Directorio espia: anota cada consulta y delega en el real.

    :param inner: Directorio real.
    :type inner: app.directory.Directory
    """

    def __init__(self, inner):
        """Guarda el directorio real.

        :param inner: Directorio real.
        :type inner: app.directory.Directory
        """
        self._inner = inner
        self.calls = []

    @property
    def departments(self):
        """Departamentos del directorio real.

        :return: Nombres de departamentos.
        :rtype: list[str]
        """
        return self._inner.departments

    def get_employee(self, employee_id):
        """Anota y delega ``get_employee``.

        :param employee_id: Id o nombre buscado.
        :type employee_id: str
        :return: Resultado del directorio real.
        :rtype: dict | str
        """
        self.calls.append(("get_employee", employee_id))
        return self._inner.get_employee(employee_id)

    def search_by_department(self, department):
        """Anota y delega ``search_by_department``.

        :param department: Departamento buscado.
        :type department: str
        :return: Resultado del directorio real.
        :rtype: list | str
        """
        self.calls.append(("search_by_department", department))
        return self._inner.search_by_department(department)


# -- SecurityAudit y metricas ---------------------------------------

def test_security_event_goes_to_log_metrics_and_trace_with_five_fields():
    """``record`` escribe el evento, suma la metrica y abre un span."""
    stream = io.StringIO()
    clock = FakeClock()
    metrics = Metrics(slo_p95_ms=SLO_P95_MS)
    tracer = RecordingTracer()
    audit = SecurityAudit(
        JsonLogger(stream=stream, service="hr", clock=clock), metrics, tracer
    )

    audit.record(
        request_id="req-1", client="tester", stage="input", control="pii",
        kinds=["email"],
    )

    (event,) = [json.loads(line) for line in stream.getvalue().splitlines()]
    expected = {
        "request_id": "req-1",
        "client": "tester",
        "stage": "input",
        "control": "pii",
        "kinds": ["email"],
    }
    assert event["event"] == "security"
    assert {key: event[key] for key in expected} == expected
    assert metrics.snapshot()["security"]["pii"] == 1
    (span,) = tracer.named("security")
    assert {key: span["metadata"][key] for key in expected} == expected


def test_security_metrics_start_at_zero_and_keep_the_previous_keys():
    """Las cinco llaves empiezan en 0, suman por evento y lo anterior no cambia."""
    metrics = Metrics(slo_p95_ms=SLO_P95_MS)
    assert metrics.snapshot()["security"] == dict.fromkeys(SECURITY_CONTROLS, 0)

    metrics.record_security("pii")
    metrics.record_security("pii")
    metrics.record_security("injection")

    snapshot = metrics.snapshot()
    assert snapshot["security"]["pii"] == 2
    assert snapshot["security"]["injection"] == 1
    previous = {"pid", "requests", "error_rate", "latency_ms", "tokens",
                "cost_usd", "slo"}
    # Spec 06, punto 7: tambien se agregan ``specialists`` y ``supervisor``.
    assert set(snapshot) == previous | {"security", "specialists", "supervisor"}


# -- Configuracion --------------------------------------------------

def test_max_answer_chars_defaults_to_2000_and_rejects_invalid_values():
    """``MAX_ANSWER_CHARS`` vale 2000 por omision y debe ser un entero positivo."""
    assert load_settings({}).max_answer_chars == 2000
    assert load_settings({"MAX_ANSWER_CHARS": "150"}).max_answer_chars == 150
    for invalid in ("0", "mucho"):
        with pytest.raises(ValueError):
            load_settings({"MAX_ANSWER_CHARS": invalid})


def test_secret_values_skip_empty_values_and_stay_out_of_repr():
    """``secret_values()`` trae las claves y el token, nunca vacios."""
    key = "acme-key-0123456789abcdef"
    without_token = Settings(
        api_keys=parse_api_keys(f"acme:{key}"), cf_api_token=SecretStr("")
    )
    assert list(without_token.secret_values()) == [key]

    with_token = Settings(
        api_keys=parse_api_keys(f"acme:{key}"), cf_api_token=SecretStr("cf-token-1")
    )
    assert sorted(with_token.secret_values()) == sorted([key, "cf-token-1"])
    assert key not in repr(with_token)
    assert "cf-token-1" not in repr(with_token)


# -- Agente ---------------------------------------------------------

def test_invalid_tool_argument_never_reaches_the_directory(directory, prices):
    """El agente no consulta el directorio, devuelve un error legible y audita."""
    spy = SpyDirectory(directory)
    audit = FakeAudit()
    stream = io.StringIO()
    agent = Agent(
        directory=spy,
        prices=prices,
        max_steps=3,
        logger=JsonLogger(stream=stream, service="hr", clock=FakeClock()),
        audit=audit,
    )
    model = BadArgsModel()

    result = agent.run("¿Quién es?", model=model, request_id="req-1", client="tester")

    assert not spy.calls
    assert len(model.tool_results) == 2
    for tool_result in model.tool_results:
        assert "error" in tool_result
    assert LONG_NAME not in "".join(model.tool_results)
    assert UNKNOWN_DEPARTMENT not in "".join(model.tool_results)
    assert [r["control"] for r in audit.records] == ["tool_args", "tool_args"]
    assert {r["stage"] for r in audit.records} == {"output"}
    assert result["tools_used"] == ["get_employee", "search_by_department"]
    # El evento ``audit`` de la sesion 2 conserva su forma.
    audits = [json.loads(ln) for ln in stream.getvalue().splitlines()]
    audits = [e for e in audits if e["event"] == "audit"]
    assert len(audits) == 2
    assert {"client", "action", "tool", "args"} <= set(audits[0])


# -- POST /ask ------------------------------------------------------

def test_ask_response_only_adds_an_empty_redactions_list(client):
    """Una pregunta normal no oculta nada y los campos anteriores no cambian."""
    response = client.post("/ask", json={"question": "¿Quién es EMP-0001?"})
    body = response.json()
    assert response.status_code == 200
    # Spec 06: se agregan ``specialist``, ``agents`` y ``supervisor_route``.
    assert set(body) == set(ASK_FIELDS) | {
        "request_id",
        "redactions",
        "specialist",
        "agents",
        "supervisor_route",
    }
    assert body["redactions"] == []


def test_unknown_tool_name_never_reaches_the_log(build_harness):
    """Un nombre de herramienta inventado no se escribe en ninguna linea del log.

    El modelo pide una herramienta desconocida con un nombre de 300
    caracteres; el log solo debe ver el valor generico.
    """
    marker = "TOOL-NAME-MARKER-"
    invented_tool = (marker + "z" * 300)[:300]
    harness = build_harness(model=BadArgsModel(requests=[(invented_tool, {})]))

    response = harness.client.post("/ask", json={"question": "Hola"})

    assert response.status_code == 200
    for line in harness.log_text().splitlines():
        assert marker not in line
    for event in harness.events("audit"):
        assert event["tool"] == UNKNOWN_TOOL_KIND
    metrics = harness.client.get("/metrics").json()
    assert metrics["security"]["tool_args"] == 1


def test_empty_model_answer_is_replaced_by_the_safe_message(build_harness):
    """Una respuesta vacia del modelo se cambia por el mensaje fijo y se audita."""
    harness = build_harness(model=EmptyAnswerModel())
    response = harness.client.post("/ask", json={"question": "Hola"})
    assert response.status_code == 200
    assert response.json()["answer"] == SAFE_FALLBACK_ANSWER
    metrics = harness.client.get("/metrics").json()
    assert metrics["security"]["output_invalid"] == 1


def test_answer_is_trimmed_to_max_answer_chars(build_harness):
    """Una respuesta larga mide exactamente ``MAX_ANSWER_CHARS``."""
    harness = build_harness(max_answer_chars=50)
    response = harness.client.post(
        "/ask", json={"question": "¿Quién trabaja en Tecnologia?"}
    )
    assert response.status_code == 200
    assert len(response.json()["answer"]) == 50
