"""Agentes LangGraph: ReAct con tope, reflexión con crítico y supervisor."""

import json

import pytest

from app.agents.react import CAP_ANSWER, NUDGE, parse_reply
from app.agents.summary import MAX_REVISIONS, critique
from app.directory import NotFoundError
from app.service import HRService
from tests.conftest import ScriptedModel, make_settings


def tool(name, **args):
    return json.dumps({"thought": f"Uso {name}.", "tool": name, "args": args})


def answer(text):
    return json.dumps({"thought": "Listo.", "answer": text})


def service(replies=None, clock=None, **env):
    model = ScriptedModel(replies) if replies is not None else None
    built = HRService(make_settings(**env), model=model, clock=clock)
    return built, model


@pytest.mark.parametrize("text, expected", [
    ('{"answer": "hola"}', {"answer": "hola"}),
    ('Claro: {"tool": "get_employee", "args": {"employee_id": "EMP-0001"}} listo',
     {"tool": "get_employee", "args": {"employee_id": "EMP-0001"}}),
    ('{"tool": "get_employee", "args": "mal"}', {"tool": "get_employee", "args": {}}),
    ("texto sin JSON", None),
    ("{no es json}", None),
    ("[1, 2]", None),
    ('{"answer": "  "}', None),
])
def test_parse_reply(text, expected):
    assert parse_reply(text) == expected


def test_react_loop_reasons_acts_and_answers(clock):
    built, model = service(
        [tool("get_employee", employee_id="EMP-0004"), answer("Es Jorge Díaz.")], clock
    )
    response = built.ask("¿Quién es EMP-0004?")
    assert response["answer"] == "Es Jorge Díaz."
    assert response["tools_used"] == ["get_employee"]
    assert response["steps"] == 2
    assert response["reasoning"] == ["Uso get_employee.", "Listo."]
    tool_result = model.calls[1][0][-1]["content"]
    assert tool_result.startswith("Resultado de la herramienta: EMP-0004: Jorge Díaz")


def test_step_cap_stops_the_loop(clock):
    looping = [tool("get_employee", employee_id="EMP-0004")] * 5
    built, _ = service(looping, clock, AGENT_MAX_STEPS="2")
    response = built.ask("¿Quién es EMP-0004?")
    assert response["answer"] == CAP_ANSWER
    assert response["steps"] == 2


def test_invalid_json_gets_one_nudge(clock):
    built, model = service(["no soy JSON", answer("Ahora sí.")], clock)
    response = built.ask("hola")
    assert response["answer"] == "Ahora sí."
    assert model.calls[1][0][-1]["content"] == NUDGE


def test_second_invalid_reply_is_used_as_plain_text(clock):
    built, _ = service(["no soy JSON", "sigo sin serlo"], clock)
    assert built.ask("hola")["answer"] == "sigo sin serlo"


def test_tool_errors_go_back_to_the_model_as_text(clock):
    built, model = service(
        [tool("delete_everything"), tool("get_employee", wrong="x"),
         answer("No pude.")], clock,
    )
    built.ask("hola")
    assert "no existe" in model.calls[1][0][-1]["content"]
    assert "Argumentos inválidos" in model.calls[2][0][-1]["content"]


def test_vacation_tool_returns_the_verified_answer_directly(clock):
    replies = [tool("get_vacation_balance", employee_id="EMP-0001")]
    built, model = service(replies, clock)
    response = built.ask("¿Cuántas vacaciones le quedan a EMP-0001?")
    assert response["agent"] == "vacation_agent"
    assert "le corresponden 22 días, ha tomado 8 y le quedan 14" in response["answer"]
    assert len(model.calls) == 1


def test_vacation_balance_overrides_an_invented_number(clock):
    built, _ = service([answer("Le quedan 99 días.")], clock)
    response = built.vacation_balance("emp-0001")
    assert "99" not in response["answer"]
    assert response["balance"]["remaining_days"] == 14
    assert "valor verificado" in response["reasoning"][-1]


def test_vacation_balance_validates_the_id(clock):
    built, _ = service(clock=clock)
    with pytest.raises(ValueError):
        built.vacation_balance("EMP-1; DROP")
    with pytest.raises(NotFoundError):
        built.vacation_balance("EMP-9999")


def test_critic_finds_missing_names_extra_numbers_and_personal_data():
    facts = ["Tiene 2 personas activas.", "Antigüedad promedio: 5.5 años."]
    assert critique("Ana y Jorge, 2 personas, 5.5 años", facts, ["Ana", "Jorge"]) == []
    problems = critique("Jorge y 40 más, ana@ejemplo.test", facts, ["Ana", "Jorge"])
    assert problems == [
        "falta mencionar a Ana", "cifras que no están en los hechos: 40",
        "falta el número de personas activas", "contiene datos personales",
    ]


def test_reflection_revises_until_the_critic_approves(clock):
    built, _ = service(clock=clock)
    response = built.department_summary("tecnologia")
    assert response["agent"] == "summary_agent"
    assert "Ana López" in response["answer"] and "Jorge Díaz" in response["answer"]
    assert response["reasoning"][0].startswith("Crítica: falta mencionar")
    assert response["reasoning"][-2:] == [
        "Crítica: sin observaciones.", "Revisiones: 1.",
    ]
    assert response["steps"] == 2


def test_reflection_falls_back_to_verified_facts(clock):
    built, model = service(["Hay 400 personas."] * (MAX_REVISIONS + 1), clock)
    response = built.department_summary("Finanzas")
    assert "400" not in response["answer"]
    assert "Sofía Gómez" in response["answer"]
    assert len(model.calls) == MAX_REVISIONS + 1
    assert "hechos verificados" in response["reasoning"][-2]


def test_unknown_department_is_not_summarized(clock):
    built, _ = service(clock=clock)
    with pytest.raises(NotFoundError):
        built.department_summary("Legal")


@pytest.mark.parametrize("question, specialist", [
    ("¿Quién es EMP-0004?", "directory_agent"),
    ("¿Cuántas vacaciones tiene EMP-0004?", "vacation_agent"),
    ("Dame un resumen de Tecnología", "summary_agent"),
    ("Resume las políticas", "directory_agent"),
])
def test_supervisor_delegates_with_a_rule(clock, question, specialist):
    built, _ = service(clock=clock)
    assert built.ask(question)["agent"] == specialist


def test_graphs_are_exported_as_mermaid(clock):
    built, _ = service(clock=clock)
    graphs = built.graphs()
    assert set(graphs) == {"supervisor", "react", "reflection"}
    assert "critique" in graphs["reflection"]
    assert "vacation_agent" in graphs["supervisor"]
