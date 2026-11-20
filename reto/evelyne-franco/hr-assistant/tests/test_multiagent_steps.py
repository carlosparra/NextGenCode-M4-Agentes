"""Pasos pytest-bdd para los escenarios del sistema multi-agente.

Cubre ``spec/06-multiagente.md``: la pregunta de vacaciones va al
especialista ``policy`` por regla y cita la politica, un numero sin
respaldo se reemplaza por el texto de la politica, la pregunta de un
empleado sigue en ``directory`` y ``/metrics`` cuenta especialistas y
motivos del supervisor sin perder las llaves de antes.

Adenda 1: con el reloj fijo, las vacaciones de un empleado se calculan
en codigo (``rule:policy_employee`` y ``vacation_days``) y un id escrito
de otra forma se reconoce.
"""

from datetime import date, datetime, time, timezone

from pytest_bdd import given, parsers, scenarios, then, when

from tests.conftest import SUPERVISOR_ROUTES_AT_ZERO, SpyModel

scenarios("features/multiagent.feature")


# -- Given ----------------------------------------------------------

@given("the HR assistant is running", target_fixture="ctx")
def assistant_running(build_harness):
    """Contexto con el modelo simulado por omision.

    :param build_harness: Fabrica de aplicaciones de prueba.
    :type build_harness: callable
    :return: Contexto del escenario.
    :rtype: dict
    """
    return {"harness": build_harness()}


@given(
    parsers.parse(
        'the HR assistant is running with a policy specialist that answers '
        '"{answer}" without tools'
    ),
    target_fixture="ctx",
)
def assistant_with_ungrounded_policy_model(build_harness, answer):
    """Contexto con un especialista simulado que contesta sin consultar.

    :param build_harness: Fabrica de aplicaciones de prueba.
    :type build_harness: callable
    :param answer: Respuesta fija del especialista.
    :type answer: str
    :return: Contexto del escenario.
    :rtype: dict
    """
    model = SpyModel(replies=[{"answer": answer}])
    return {"harness": build_harness(model=model), "model": model}


def _clock_at(day):
    """Convierte ``AAAA-MM-DD`` en un instante UTC al mediodia.

    :param day: Fecha del reloj fijo.
    :type day: str
    :return: Instante con zona horaria UTC.
    :rtype: datetime.datetime
    """
    return datetime.combine(
        date.fromisoformat(day), time(12, 0), tzinfo=timezone.utc
    )


@given(
    parsers.re(r'the HR assistant is running on "(?P<day>[\d-]+)"$'),
    target_fixture="ctx",
)
def assistant_running_on(build_harness, day):
    """Adenda 1: contexto con el reloj fijo en una fecha.

    :param build_harness: Fabrica de aplicaciones de prueba.
    :type build_harness: callable
    :param day: Fecha del reloj, por ejemplo ``2026-11-19``.
    :type day: str
    :return: Contexto del escenario.
    :rtype: dict
    """
    return {"harness": build_harness(now=_clock_at(day))}


@given(
    parsers.re(
        r'the HR assistant is running on "(?P<day>[\d-]+)" with a policy '
        r'specialist that answers "(?P<answer>[^"]+)"$'
    ),
    target_fixture="ctx",
)
def assistant_on_with_policy_model(build_harness, day, answer):
    """Adenda 1: reloj fijo y un especialista que contesta sin herramientas.

    La consulta de ``rule:policy_employee`` se hace en codigo igual.

    :param build_harness: Fabrica de aplicaciones de prueba.
    :type build_harness: callable
    :param day: Fecha del reloj.
    :type day: str
    :param answer: Respuesta fija del especialista.
    :type answer: str
    :return: Contexto del escenario.
    :rtype: dict
    """
    model = SpyModel(replies=[{"answer": answer}])
    harness = build_harness(model=model, now=_clock_at(day))
    return {"harness": harness, "model": model}


# -- When -----------------------------------------------------------

@when(parsers.re(r'I ask "(?P<question>[^"]+)"$'))
def ask(ctx, question):
    """Hace una pregunta sin historial.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param question: Texto de la pregunta.
    :type question: str
    """
    ctx["response"] = ctx["harness"].client.post("/ask", json={"question": question})


# -- Then -----------------------------------------------------------

@then(parsers.parse("the response status is {code:d}"))
def check_status(ctx, code):
    """Verifica el codigo HTTP.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param code: Codigo esperado.
    :type code: int
    """
    assert ctx["response"].status_code == code, ctx["response"].text


@then(
    parsers.parse(
        'the specialist is "{specialist}" with supervisor route "{route}"'
    )
)
def check_specialist(ctx, specialist, route):
    """Verifica el especialista y el motivo del supervisor.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param specialist: ``directory`` o ``policy``.
    :type specialist: str
    :param route: Motivo esperado, por ejemplo ``rule:policy``.
    :type route: str
    """
    body = ctx["response"].json()
    assert body["specialist"] == specialist
    assert body["supervisor_route"] == route


@then(parsers.parse('the agents are "{agents}"'))
def check_agents(ctx, agents):
    """Verifica los agentes que corrieron, en orden.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param agents: Nombres separados por coma.
    :type agents: str
    """
    expected = [name.strip() for name in agents.split(",")]
    assert ctx["response"].json()["agents"] == expected


@then(parsers.parse('the answer mentions "{text}"'))
def answer_mentions(ctx, text):
    """Verifica que la respuesta incluya un texto.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param text: Texto esperado.
    :type text: str
    """
    assert text in ctx["response"].json()["answer"]


@then(parsers.parse('the answer does not mention "{text}"'))
def answer_does_not_mention(ctx, text):
    """Verifica que la respuesta no incluya un texto.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param text: Texto que no debe aparecer.
    :type text: str
    """
    assert text not in ctx["response"].json()["answer"]


@then(parsers.parse('the answer is "{text}"'))
def answer_is(ctx, text):
    """Adenda 1: verifica la respuesta completa.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param text: Respuesta esperada.
    :type text: str
    """
    assert ctx["response"].json()["answer"] == text


@then(parsers.parse('the tools used are "{tools}"'))
def check_tools_used(ctx, tools):
    """Adenda 1: verifica las herramientas usadas, en orden.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param tools: Nombres separados por coma.
    :type tools: str
    """
    expected = [name.strip() for name in tools.split(",")]
    assert ctx["response"].json()["tools_used"] == expected


@then("the policy was looked up in code with an audit event")
def policy_looked_up_in_code(ctx):
    """Verifica que ``search_policy`` corrio y dejo su ``audit``.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    """
    body = ctx["response"].json()
    assert "search_policy" in body["tools_used"]
    audits = [
        e
        for e in ctx["harness"].events("audit")
        if e["request_id"] == body["request_id"]
    ]
    assert [(e["action"], e["tool"]) for e in audits] == [
        ("tool_call", "search_policy")
    ]


@then(
    parsers.parse(
        'there is an output security event "{control}" with kinds "{kind}"'
    )
)
def output_security_event(ctx, control, kind):
    """Verifica un evento ``security`` de salida, sin el valor.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param control: Control esperado, por ejemplo ``ungrounded``.
    :type control: str
    :param kind: Tipo esperado en ``kinds``.
    :type kind: str
    """
    events = [
        e for e in ctx["harness"].events("security") if e["control"] == control
    ]
    assert len(events) == 1
    assert events[0]["stage"] == "output"
    assert events[0]["kinds"] == [kind]
    # El evento nunca lleva el valor sin respaldo.
    assert "30 días" not in str(events[0])


@then(
    parsers.parse(
        'the metrics count {first:d} answer from "{one}" and {second:d} from "{two}"'
    )
)
def metrics_count_specialists(ctx, first, one, second, two):
    """Verifica el conteo por especialista de ``GET /metrics``.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param first: Conteo del primer especialista.
    :type first: int
    :param one: Primer especialista.
    :type one: str
    :param second: Conteo del segundo especialista.
    :type second: int
    :param two: Segundo especialista.
    :type two: str
    """
    snapshot = ctx["harness"].client.get("/metrics").json()
    assert snapshot["specialists"] == {one: first, two: second}


@then(
    parsers.parse(
        'the metrics count {first:d} supervisor route "{one}" '
        'and {second:d} "{two}"'
    )
)
def metrics_count_routes(ctx, first, one, second, two):
    """Verifica el conteo por motivo del supervisor; el resto en 0.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param first: Conteo del primer motivo.
    :type first: int
    :param one: Primer motivo.
    :type one: str
    :param second: Conteo del segundo motivo.
    :type second: int
    :param two: Segundo motivo.
    :type two: str
    """
    snapshot = ctx["harness"].client.get("/metrics").json()
    assert snapshot["supervisor"] == {
        **SUPERVISOR_ROUTES_AT_ZERO,
        one: first,
        two: second,
    }


@then(parsers.parse('the metrics keep the keys "{keys}"'))
def metrics_keep_keys(ctx, keys):
    """Verifica que las llaves de las sesiones anteriores siguen ahi.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param keys: Llaves separadas por coma.
    :type keys: str
    """
    snapshot = ctx["harness"].client.get("/metrics").json()
    for key in (name.strip() for name in keys.split(",")):
        assert key in snapshot
