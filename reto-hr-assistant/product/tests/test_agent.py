"""Pruebas unitarias del agente con un modelo guionado."""

import json

from app.agent import FALLBACK_ANSWER, Agent

TOOL_PREFIX = "Resultado de la herramienta: "


def tool_call(name, **args):
    """Arma la respuesta del modelo que pide una herramienta.

    :param name: Nombre de la herramienta
    :type name: str
    :return: Objeto JSON como texto
    :rtype: str
    """
    return json.dumps({"tool": name, "args": args})


def answer(text):
    """Arma la respuesta final del modelo.

    :param text: Respuesta en español
    :type text: str
    :return: Objeto JSON como texto
    :rtype: str
    """
    return json.dumps({"answer": text}, ensure_ascii=False)


def test_tool_result_is_sent_back_with_the_exact_prefix(directory, scripted_model):
    model = scripted_model(
        [tool_call("get_employee", employee_id="EMP-0004"), answer("Listo")]
    )

    result = Agent(model, directory, max_steps=3).run("¿Quién es EMP-0004?", [])

    last_message = model.calls[1][-1]
    assert last_message["role"] == "user"
    assert last_message["content"].startswith(TOOL_PREFIX)
    assert "Jorge Díaz" in last_message["content"]
    assert result.answer == "Listo"
    assert result.steps == 2
    assert result.tools_used == ["get_employee"]
    assert (result.input_tokens, result.output_tokens) == (20, 4)


def test_invalid_model_output_is_reported_back_without_breaking(
    directory, scripted_model
):
    model = scripted_model(["esto no es JSON", answer("Corregido")])

    result = Agent(model, directory, max_steps=3).run("Hola", [])

    assert model.calls[1][-1]["content"].startswith(TOOL_PREFIX)
    assert result.answer == "Corregido"
    assert result.steps == 2


def test_unknown_tool_until_the_cap_returns_the_fallback_answer(
    directory, scripted_model
):
    model = scripted_model([tool_call("delete_employee", employee_id="EMP-0001")] * 2)

    result = Agent(model, directory, max_steps=2).run("Borra a EMP-0001", [])

    assert result.answer == FALLBACK_ANSWER
    assert result.steps == 2
    assert "delete_employee" in model.calls[1][-1]["content"]
    assert FALLBACK_ANSWER == (
        "No pude completar la respuesta. Intenta con una pregunta más concreta."
    )


def test_agent_reports_whether_it_answered_or_hit_the_cap(directory, scripted_model):
    answered = Agent(scripted_model([answer("Hola")]), directory, max_steps=3)
    capped = Agent(
        scripted_model([tool_call("get_employee", employee_id="EMP-0004")]),
        directory,
        max_steps=1,
    )

    answered_result = answered.run("Hola", [])
    capped_result = capped.run("¿Quién es EMP-0004?", [])

    assert answered_result.stopped == "answer"
    assert capped_result.stopped == "max_steps"
    assert capped_result.answer == FALLBACK_ANSWER


def test_only_valid_tool_calls_are_announced_in_order(directory, scripted_model):
    announced = []
    model = scripted_model(
        [
            tool_call("get_employee", employee_id="EMP-0004"),
            tool_call("delete_employee", employee_id="EMP-0001"),
            tool_call("get_employee", id="EMP-0001"),
            tool_call("search_by_department", department="Ventas"),
            answer("Listo"),
        ]
    )

    Agent(model, directory, max_steps=5).run(
        "¿Quién es EMP-0004?",
        [],
        on_tool_call=lambda tool, args: announced.append((tool, args)),
    )

    assert announced == [
        ("get_employee", {"employee_id": "EMP-0004"}),
        ("search_by_department", {"department": "Ventas"}),
    ]
