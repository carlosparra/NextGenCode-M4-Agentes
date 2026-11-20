"""Pruebas de minimo privilegio entre especialistas (spec 06, punto 2).

``policy`` solo tiene ``search_policy`` y ``directory`` solo tiene
``get_employee`` y ``search_by_department``. Una herramienta ajena se
trata como desconocida: no se ejecuta y deja ``security`` con
``control=tool_args``.
"""

from tests.conftest import SpyModel


def _tool_args_events(harness):
    """Devuelve los eventos ``security`` de argumentos de herramienta.

    :param harness: Arnes de la aplicacion.
    :type harness: tests.conftest.Harness
    :return: Eventos con ``control=tool_args``.
    :rtype: list[dict]
    """
    return [e for e in harness.events("security") if e["control"] == "tool_args"]


def test_the_policy_specialist_cannot_read_the_directory(build_harness):
    """``get_employee`` desde ``policy`` no devuelve datos del empleado."""
    spy = SpyModel(
        replies=[
            {"tool": "get_employee", "args": {"employee_id": "EMP-0001"}},
            {"answer": "Listo."},
        ]
    )
    harness = build_harness(model=spy)

    response = harness.client.post(
        "/ask", json={"question": "¿Cuántos días de vacaciones tengo?"}
    )

    assert response.status_code == 200
    assert response.json()["specialist"] == "policy"
    assert "Ana Lopez" not in spy.specialist_text()
    assert len(_tool_args_events(harness)) == 1


def test_the_directory_specialist_cannot_read_the_policies(build_harness):
    """``search_policy`` desde ``directory`` no devuelve el texto de la politica."""
    spy = SpyModel(
        replies=[
            {"tool": "search_policy", "args": {"topic": "vacaciones"}},
            {"answer": "Listo."},
        ]
    )
    harness = build_harness(model=spy)

    response = harness.client.post("/ask", json={"question": "¿Quién es EMP-0001?"})

    assert response.status_code == 200
    assert response.json()["specialist"] == "directory"
    assert "12 días hábiles" not in spy.specialist_text()
    assert len(_tool_args_events(harness)) == 1
