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


def test_system_prompt_tells_the_model_to_answer_after_a_tool_result():
    """El prompt de sistema evita que un modelo pequeño encadene herramientas.

    Hallazgo en producción: con el modelo de 8B el agente llegaba al tope de
    pasos porque volvía a pedir herramientas tras recibir el resultado.

    Contrato para developer: ``SYSTEM_PROMPT`` debe contener, sin importar
    mayúsculas, estas frases clave (el resto del texto es libre):

    (a) ``"resultado de la herramienta"``, ``'{"answer"'`` y ``"de inmediato"``:
        tras un resultado de herramienta responde de inmediato con
        ``{"answer": ...}`` si ya tiene los datos.
    (b) ``"una sola herramienta"``: usa una sola herramienta salvo que falte
        información.
    (c) ``"última pregunta"``: responde solo la última pregunta.
    (d) ``"datos ocultos"`` y los cinco marcadores ``[EMAIL]``, ``[PHONE]``,
        ``[CURP]``, ``[RFC]`` y ``[CARD]``: son datos ocultos que no se buscan
        con herramientas.
    """
    prompt = SYSTEM_PROMPT.lower()
    key_phrases = (
        "resultado de la herramienta",
        '{"answer"',
        "de inmediato",
        "una sola herramienta",
        "última pregunta",
        "datos ocultos",
    )
    missing = [phrase for phrase in key_phrases if phrase not in prompt]
    missing += [
        marker
        for marker in ("[EMAIL]", "[PHONE]", "[CURP]", "[RFC]", "[CARD]")
        if marker not in SYSTEM_PROMPT
    ]

    assert not missing, f"faltan frases clave en SYSTEM_PROMPT: {missing}"
