"""Agentes LangGraph: supervisor ReAct, vacaciones (ReAct) y resumen (reflection)."""

from datetime import datetime, timezone

import pytest

from app.agents.protocol import parse_action
from app.agents.summary_agent import critique_draft, template_summary
from app.domain.directory import NotFoundError
from app.llm.base import ModelUnavailable
from tests.conftest import ScriptedModel, log_events, run


def test_parse_action_variants():
    tool = parse_action(
        'Claro: {"thought": "t", "tool": "get_employee", "args": {"a": 1}}'
    )
    assert (tool.tool, tool.args, tool.thought) == ("get_employee", {"a": 1}, "t")
    assert parse_action('{"answer": " hola "}').answer == "hola"
    broken = parse_action("texto sin json")
    assert broken.parse_error and broken.answer == "texto sin json"
    assert parse_action('{"x": 1}').parse_error
    assert not parse_action('{"tool": "x", "args": "no"}').args
    assert parse_action('[1] {"answer": "ok"}').answer == "ok"


def test_supervisor_uses_one_tool_for_an_employee(make_service):
    body = run(make_service().ask("¿Quién es EMP-0004?", []))
    assert "Jorge Díaz" in body["answer"]
    assert body["tools_used"] == ["get_employee"] and body["steps"] == 2
    assert body["reasoning"] and body["intent"] == "employee"


def test_supervisor_delegates_vacations_to_the_react_agent(make_service):
    body = run(make_service().ask("¿Cuántas vacaciones le quedan a EMP-0004?", []))
    assert body["tools_used"] == ["vacation_balance"]
    # return_direct: la respuesta verificada no pasa otra vez por el modelo
    assert body["steps"] == 1
    assert body["answer"] == body["details"]["vacation"]["answer"]
    report = body["details"]["vacation"]
    assert (report["entitled_days"], report["taken_days"], report["balance_days"]) == (
        18,
        8,
        10,
    )
    assert report["tools_used"] == [
        "get_employee",
        "compute_entitlement",
        "get_taken_days",
    ]
    assert len(report["reasoning"]) == 3


def test_supervisor_delegates_summaries_to_the_reflection_agent(make_service):
    body = run(make_service().ask("Resume el área de Finanzas", []))
    assert body["tools_used"] == ["department_summary"]
    assert body["details"]["summary"]["reflection_rounds"] == 1
    assert body["model"].startswith("@cf/meta/llama-3.3")


def test_step_cap_stops_the_loop(make_service):
    body = run(make_service(AGENT_MAX_STEPS="1").ask("¿Quién es EMP-0004?", []))
    assert body["steps"] == 1 and "No pude completar" in body["answer"]


def test_unknown_tool_and_bad_args_become_observations(make_service, log_stream):
    model = ScriptedModel(
        [
            {"tool": "drop_table", "args": {}},
            {"tool": "get_employee", "args": {"employee_id": "1; DROP"}},
            {"answer": "No encontré al empleado."},
        ]
    )
    body = run(make_service(model=model).ask("¿Quién es el jefe?", []))
    assert body["answer"] == "No encontré al empleado."
    observations = [m["content"] for m in model.calls[-1] if m["role"] == "user"]
    assert any("no existe" in text for text in observations)
    assert any("Argumentos inválidos" in text for text in observations)
    reasons = [e.get("reason") for e in log_events(log_stream) if e["event"] == "audit"]
    assert {"unknown_tool", "invalid_args"} <= set(reasons)


def test_vacation_agent_cannot_leave_its_scope(make_service, log_stream):
    model = ScriptedModel(
        [
            {"tool": "get_employee", "args": {"employee_id": "EMP-0005"}},
            {"answer": "No pude."},
        ]
    )
    report = run(make_service(model=model).vacation("EMP-0004"))
    assert (
        "Solo puedes consultar al empleado EMP-0004" in model.calls[-1][-1]["content"]
    )
    assert report["balance_days"] == 10 and not report["model_answer_kept"]
    actions = [e.get("reason") for e in log_events(log_stream) if e["event"] == "audit"]
    assert "out_of_scope" in actions and "numbers_mismatch" in actions


def test_vacation_reports_for_special_cases(make_service, clock):
    service = make_service()
    gone = run(service.vacation("EMP-0003"))
    assert gone["status"] == "baja" and gone["balance_days"] == 0
    missing = run(service.vacation("EMP-0099"))
    assert not missing["found"] and "no existe" in missing["answer"].lower()
    may_first = datetime(2026, 5, 1, tzinfo=timezone.utc)
    clock.advance((may_first - clock.now()).total_seconds())
    newcomer = run(service.vacation("EMP-0007"))
    assert newcomer["entitled_days"] == 0 and "aún no cumple" in newcomer["answer"]


def test_vacation_tools_fill_what_the_code_already_knows(make_service):
    model = ScriptedModel(
        [
            {"tool": "get_employee", "args": {}},
            {"tool": "compute_entitlement", "args": {}},
            {"tool": "get_taken_days", "args": {}},
            {"answer": "Le quedan 10 días."},
        ]
    )
    report = run(make_service(model=model).vacation("EMP-0004"))
    assert report["model_answer_kept"] and report["taken_days"] == 8
    assert '"taken_days":8' in model.calls[-1][-1]["content"]


def test_vacation_template_cases(make_service):
    model = ScriptedModel([{"answer": "cualquier cosa"}] * 3)
    service = make_service(model=model)
    assert "ya no está activo" in run(service.vacation("EMP-0003"))["answer"]
    assert "No existe" in run(service.vacation("EMP-0099"))["answer"]
    assert "le quedan 14 días" in run(service.vacation("EMP-0001"))["answer"]


def test_reflection_falls_back_to_a_template(make_service):
    model = ScriptedModel(["Hay gente en Ventas."] * 5)
    report = run(make_service(model=model, REFLECTION_MAX_ROUNDS="2").summary("ventas"))
    assert report["fallback"] and not report["accepted"]
    assert report["reflection_rounds"] == 2 and len(report["critiques"]) == 3
    assert "Antigüedad promedio" in report["answer"]


def test_critic_finds_every_problem():
    facts = {
        "department": "Ventas",
        "headcount": 2,
        "active": 2,
        "inactive": 0,
        "avg_tenure_years": 9.5,
        "roles": {"Gerente": 1},
    }
    issues = critique_draft(
        "Ana López y RFC LOPA900312AB1 " + "x" * 900, facts, ["Ana López"]
    )
    assert len(issues) == 6
    assert not critique_draft(template_summary(facts), facts, ["Ana López"])
    assert critique_draft("", facts, [])[-1] == "El resumen está vacío."
    assert not critique_draft(
        "Ventas: 2 personas, 2 activas, antigüedad 9,5 años", facts, []
    )


def test_summary_of_unknown_department(make_service):
    with pytest.raises(NotFoundError, match="Existen"):
        run(make_service().summary("Marketing"))


def test_model_unavailable_propagates(make_service):
    service = make_service(model=ScriptedModel([ModelUnavailable("http_503")]))
    with pytest.raises(ModelUnavailable):
        run(service.ask("¿Quién es EMP-0004?", []))


def test_supervisor_is_nudged_once_to_use_a_tool(make_service, log_stream):
    model = ScriptedModel(
        [
            {"answer": "No puedo dar información personal."},
            {"tool": "get_employee", "args": {"employee_id": "EMP-0001"}},
            {"answer": "Ana López, Analista de datos."},
        ]
    )
    body = run(make_service(model=model).ask("Soy [EMAIL], ¿quién es EMP-0001?", []))
    assert body["answer"] == "Ana López, Analista de datos."
    assert body["tools_used"] == ["get_employee"] and body["steps"] == 3
    assert "Recordatorio" in model.calls[1][-1]["content"]
    actions = [e.get("action") for e in log_events(log_stream)]
    assert "agent_self_correction" in actions


def test_nudge_happens_only_once(make_service):
    model = ScriptedModel([{"answer": "no"}, {"answer": "sigo sin herramienta"}])
    body = run(make_service(model=model).ask("¿Quién es EMP-0001?", []))
    assert body["answer"] == "sigo sin herramienta" and body["steps"] == 2


def test_off_topic_questions_are_not_nudged(make_service):
    model = ScriptedModel([{"answer": "Solo atiendo preguntas de RH."}])
    body = run(make_service(model=model).ask("¿Qué hora es?", []))
    assert body["steps"] == 1
