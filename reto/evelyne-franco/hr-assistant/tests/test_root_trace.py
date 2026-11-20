"""Pruebas de la traza raiz por peticion (spec 06, punto 6).

Usa ``TreeTracer``, un trazador espia que arma el arbol de runs. Cada
``POST /ask`` abre una sola raiz ``request`` con, en orden,
``agent.guard``, ``agent.supervisor``, el especialista y
``agent.reviewer``. Los agentes de codigo no reciben texto y su salida es
un resumen.
"""

from tests.conftest import (
    ADENDA_NOW,
    TEST_CLIENT,
    TEST_KEY,
    SecretLeakingModel,
    TreeTracer,
)

VACATION_QUESTION = "¿Cuántos días de vacaciones tengo?"
EMPLOYEE_VACATION_QUESTION = "¿Cuántos días de vacaciones tiene EMP-0004?"
EMAIL_QUESTION = "Soy ana@empresa.com, ¿cuántos días de vacaciones tengo?"
NO_RULE_QUESTION = "Hola, ¿cómo estás?"
CODE_AGENTS = ("request", "agent.guard", "agent.supervisor", "agent.reviewer")


def _ask(harness, question):
    """Hace una pregunta y devuelve el cuerpo, exigiendo 200.

    :param harness: Arnes de la aplicacion.
    :type harness: tests.conftest.Harness
    :param question: Texto de la pregunta.
    :type question: str
    :return: Cuerpo JSON de la respuesta.
    :rtype: dict
    """
    response = harness.client.post("/ask", json={"question": question})
    assert response.status_code == 200, response.text
    return response.json()


def test_each_request_opens_one_root_with_the_agents_in_order(build_harness):
    """Una raiz por peticion; modelo y herramientas quedan en su agente.

    La primera pregunta va a ``policy`` por regla; la segunda no tiene
    regla, asi que el supervisor llama al modelo dentro de su run.
    """
    tracer = TreeTracer()
    harness = build_harness(tracer=tracer)

    _ask(harness, VACATION_QUESTION)
    _ask(harness, NO_RULE_QUESTION)

    roots = tracer.roots()
    assert [(r["name"], r["run_type"]) for r in roots] == [("request", "chain")] * 2
    policy_root, directory_root = roots
    assert [c["name"] for c in tracer.children(policy_root)] == [
        "agent.guard",
        "agent.supervisor",
        "agent.policy",
        "agent.reviewer",
    ]
    assert [c["name"] for c in tracer.children(directory_root)] == [
        "agent.guard",
        "agent.supervisor",
        "agent.directory",
        "agent.reviewer",
    ]
    policy_agent = tracer.child_named(policy_root, "agent.policy")
    assert "search_policy" in [r["name"] for r in tracer.descendants(policy_agent)]
    supervisor = tracer.child_named(directory_root, "agent.supervisor")
    assert [r["run_type"] for r in tracer.children(supervisor)] == ["llm"]


def test_vacations_by_employee_trace_both_tools_inside_the_policy_agent(
    build_harness,
):
    """Adenda 1: la ruta ``rule:policy_employee`` deja las dos herramientas
    como runs ``tool`` dentro de ``agent.policy``.
    """
    tracer = TreeTracer()
    harness = build_harness(tracer=tracer, now=ADENDA_NOW)

    body = _ask(harness, EMPLOYEE_VACATION_QUESTION)

    assert body["supervisor_route"] == "rule:policy_employee"
    (root,) = tracer.roots()
    assert (root["name"], root["run_type"]) == ("request", "chain")
    assert [c["name"] for c in tracer.children(root)] == [
        "agent.guard",
        "agent.supervisor",
        "agent.policy",
        "agent.reviewer",
    ]
    policy_agent = tracer.child_named(root, "agent.policy")
    tools = [
        r["name"] for r in tracer.descendants(policy_agent) if r["run_type"] == "tool"
    ]
    assert tools == ["search_policy", "vacation_days"]


def test_security_spans_stay_inside_the_guard_and_the_reviewer(build_harness):
    """El correo de la entrada queda en ``agent.guard``; la clave filtrada
    en la salida queda en ``agent.reviewer``.
    """
    input_tracer = TreeTracer()
    _ask(build_harness(tracer=input_tracer), EMAIL_QUESTION)
    output_tracer = TreeTracer()
    leaking = build_harness(tracer=output_tracer, model=SecretLeakingModel())
    _ask(leaking, "¿Quién es EMP-0001?")

    (input_root,) = input_tracer.roots()
    guard = input_tracer.child_named(input_root, "agent.guard")
    assert [
        s["metadata"]["control"]
        for s in input_tracer.children(guard)
        if s["name"] == "security"
    ] == ["pii"]
    (output_root,) = output_tracer.roots()
    reviewer = output_tracer.child_named(output_root, "agent.reviewer")
    assert "secret" in [
        s["metadata"]["control"]
        for s in output_tracer.children(reviewer)
        if s["name"] == "security"
    ]


def test_every_run_carries_request_id_and_client_and_never_the_key(build_harness):
    """El raiz y el especialista llevan ademas ``specialist`` y la ruta."""
    tracer = TreeTracer()
    harness = build_harness(tracer=tracer)

    body = _ask(harness, VACATION_QUESTION)

    assert tracer.runs
    for run in tracer.runs:
        assert run["metadata"]["request_id"] == body["request_id"], run["name"]
        assert run["metadata"]["client"] == TEST_CLIENT, run["name"]
    (root,) = tracer.roots()
    for run in (root, tracer.child_named(root, "agent.policy")):
        assert run["metadata"]["specialist"] == "policy"
        assert run["metadata"]["supervisor_route"] == "rule:policy"
    assert TEST_KEY not in repr(tracer.runs)


def test_code_agents_take_no_text_and_return_only_a_summary(build_harness):
    """El raiz, guard, supervisor y reviewer no reciben ni devuelven la pregunta."""
    tracer = TreeTracer()
    harness = build_harness(tracer=tracer)

    _ask(harness, EMAIL_QUESTION)

    code_runs = [run for run in tracer.runs if run["name"] in CODE_AGENTS]
    assert sorted(run["name"] for run in code_runs) == sorted(CODE_AGENTS)
    for run in code_runs:
        assert run["args"] == () and run["kwargs"] == {}, run["name"]
        output = repr(run["result"])
        assert "ana@empresa.com" not in output, run["name"]
        assert "tengo" not in output, run["name"]
