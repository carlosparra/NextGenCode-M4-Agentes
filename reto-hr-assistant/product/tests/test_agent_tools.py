"""Pruebas de cómo el agente y el modelo simulado conocen las herramientas nuevas."""

import json

from app.agent import SYSTEM_PROMPT
from app.llm import FakeModel

DEPARTMENTS = ["Tecnología", "Ventas", "Finanzas"]


def _fake_decision(question):
    """Devuelve el objeto JSON que el modelo simulado responde a una pregunta.

    :rtype: dict
    """
    reply = FakeModel(DEPARTMENTS).complete([{"role": "user", "content": question}])
    return json.loads(reply.text)


def test_fake_model_asks_vacation_balance_for_a_vacation_question():
    decision = _fake_decision("¿Cuántos días de vacaciones le quedan a EMP-0004?")

    assert decision == {
        "tool": "get_vacation_balance",
        "args": {"employee_id": "EMP-0004"},
    }


def test_fake_model_asks_department_summary_for_a_summary_question():
    decision = _fake_decision("Dame el resumen del departamento de Ventas")

    assert decision == {"tool": "department_summary", "args": {"department": "Ventas"}}


def test_system_prompt_describes_the_four_tools_with_their_arguments():
    for signature in (
        "get_employee(employee_id)",
        "search_by_department(department)",
        "get_vacation_balance(employee_id)",
        "department_summary(department)",
    ):
        assert signature in SYSTEM_PROMPT
