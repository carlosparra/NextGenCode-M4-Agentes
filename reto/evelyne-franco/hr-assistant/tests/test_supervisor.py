"""Pruebas del supervisor: reglas antes que modelo (spec 06, punto 1).

Las reglas son, en orden, ``rule:employee`` (id ``EMP-dddd``),
``rule:department`` (departamento del directorio) y ``rule:policy``
(palabra clave de una politica), sin acentos ni mayusculas; desde la
Adenda 1, ``rule:policy_employee`` (id y tema ``vacaciones``) va antes
de ``rule:employee``. Si ninguna
aplica, el supervisor hace **una** llamada a ``MODEL_SMALL`` sin
historial. Un ``SpyModel`` cuenta las llamadas del supervisor.
"""

from tests.conftest import (
    MODEL_LARGE,
    MODEL_SMALL,
    SUPERVISOR_INPUT_TOKENS,
    SUPERVISOR_OUTPUT_TOKENS,
    SpyModel,
)

NO_RULE_QUESTION = "Hola, ¿cómo estás?"
# Texto libre, JSON sin ``specialist`` y un especialista que no existe.
INVALID_REPLIES = (
    "Creo que es de directorio",
    '{"answer": "hola"}',
    '{"specialist": "payroll"}',
)


def _ask(harness, question, history=None):
    """Hace una pregunta y devuelve el cuerpo, exigiendo 200.

    :param harness: Arnes de la aplicacion.
    :type harness: tests.conftest.Harness
    :param question: Texto de la pregunta.
    :type question: str
    :param history: Historial opcional.
    :type history: list[dict[str, str]] | None
    :return: Cuerpo JSON de la respuesta.
    :rtype: dict
    """
    payload = {"question": question}
    if history is not None:
        payload["history"] = history
    response = harness.client.post("/ask", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_a_department_routes_to_directory_ignoring_accents_and_case(build_harness):
    """``TECNOLOGÍA`` coincide con ``Tecnologia`` y no se llama al modelo."""
    spy = SpyModel()
    harness = build_harness(model=spy)

    body = _ask(harness, "¿Quiénes están en TECNOLOGÍA?")

    assert body["specialist"] == "directory"
    assert body["supervisor_route"] == "rule:department"
    assert not spy.supervisor_calls


def test_a_policy_keyword_routes_to_policy_ignoring_accents_and_case(build_harness):
    """``DÍAS LIBRES`` es palabra clave de vacaciones y no se llama al modelo."""
    spy = SpyModel()
    harness = build_harness(model=spy)

    body = _ask(harness, "¿Me quedan DÍAS LIBRES este año?")

    assert body["specialist"] == "policy"
    assert body["supervisor_route"] == "rule:policy"
    assert not spy.supervisor_calls


def test_rules_apply_in_order_employee_then_department_then_policy(build_harness):
    """Un id gana a una politica y un departamento tambien.

    Adenda 1: con un id y el tema ``vacaciones`` la regla es
    ``rule:policy_employee``, asi que aqui se usa el aguinaldo.
    """
    spy = SpyModel()
    harness = build_harness(model=spy)

    by_employee = _ask(harness, "¿EMP-0001 ya cobró su aguinaldo?")
    by_department = _ask(harness, "¿En Ventas cuántas vacaciones dan?")

    assert by_employee["supervisor_route"] == "rule:employee"
    assert by_employee["specialist"] == "directory"
    assert by_department["supervisor_route"] == "rule:department"
    assert by_department["specialist"] == "directory"
    assert not spy.supervisor_calls


def test_without_a_rule_the_small_model_is_called_once_without_history(
    build_harness,
):
    """Una sola llamada a ``MODEL_SMALL``: prompt de sistema y pregunta.

    Los tokens del supervisor suman a los del especialista en ``/ask``.
    """
    spies = {}

    def factory(name):
        spies[name] = SpyModel(
            name=name,
            supervisor_reply='{"specialist": "policy"}',
            replies=[{"answer": "Pregunta a Recursos Humanos."}],
        )
        return spies[name]

    harness = build_harness(model_factory=factory)
    history = [
        {"role": "user", "content": "Buenos días"},
        {"role": "assistant", "content": "Hola, ¿en qué te ayudo?"},
    ]

    body = _ask(harness, NO_RULE_QUESTION, history=history)

    assert body["specialist"] == "policy"
    assert body["supervisor_route"] == "model"
    assert len(spies[MODEL_SMALL].supervisor_calls) == 1
    assert not spies[MODEL_LARGE].supervisor_calls
    call = spies[MODEL_SMALL].supervisor_calls[0]
    assert [m["role"] for m in call] == ["system", "user"]
    assert call[-1]["content"] == NO_RULE_QUESTION
    # El especialista respondio en una llamada de 1 token de entrada y 1 de salida.
    assert body["input_tokens"] == SUPERVISOR_INPUT_TOKENS + 1
    assert body["output_tokens"] == SUPERVISOR_OUTPUT_TOKENS + 1


def test_an_employee_id_with_vacations_routes_to_policy_without_the_model(
    build_harness,
):
    """Adenda 1, A2: la regla nueva va antes de ``rule:employee``.

    Aplica tambien con un id escrito de otra forma y con un departamento
    en la pregunta, y ``/metrics`` la cuenta en ``supervisor``.
    """
    spy = SpyModel()
    harness = build_harness(model=spy)

    canonical = _ask(harness, "¿Cuántos días de vacaciones tiene EMP-0002?")
    other_form = _ask(harness, "¿Cuántas vacaciones tiene el emp-2 de Ventas?")

    for body in (canonical, other_form):
        assert body["specialist"] == "policy"
        assert body["supervisor_route"] == "rule:policy_employee"
    assert not spy.supervisor_calls
    snapshot = harness.client.get("/metrics").json()
    assert snapshot["supervisor"]["rule:policy_employee"] == 2


def test_an_employee_id_with_the_vacation_bonus_stays_with_the_directory(
    build_harness,
):
    """Adenda 1, decision 1: la prima vacacional no es el tema ``vacaciones``."""
    harness = build_harness()

    body = _ask(harness, "¿Cuánto es la prima de vacaciones de EMP-0004?")

    assert body["specialist"] == "directory"
    assert body["supervisor_route"] == "rule:employee"


def test_an_invalid_supervisor_answer_falls_back_to_directory(build_harness):
    """Texto libre, JSON sin ``specialist`` o un especialista desconocido."""
    for reply in INVALID_REPLIES:
        spy = SpyModel(supervisor_reply=reply)
        harness = build_harness(model=spy)

        body = _ask(harness, NO_RULE_QUESTION)

        assert body["specialist"] == "directory", reply
        assert body["supervisor_route"] == "model_invalid", reply
        assert len(spy.supervisor_calls) == 1
