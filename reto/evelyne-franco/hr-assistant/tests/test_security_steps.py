"""Pasos pytest-bdd para los escenarios de seguridad reforzada.

Cubre ``spec/05-security-hardening.md``: PII en la pregunta y el
historial (el modelo, el log y la traza solo ven el texto limpio), datos
del directorio que nunca se ocultan, inyeccion que se audita sin
bloquear, argumentos de herramientas invalidos y claves que el modelo
filtra en su respuesta.
"""

from pytest_bdd import given, parsers, scenarios, then, when

from tests.conftest import (
    LONG_NAME,
    TEST_KEY,
    BadArgsModel,
    RecordingModel,
    RecordingTracer,
    SecretLeakingModel,
)

scenarios("features/security.feature")

EMAIL = "ana@empresa.com"


# -- Given ----------------------------------------------------------

@given("the HR assistant is running with a recording model", target_fixture="ctx")
def assistant_with_recording_model(build_harness):
    """Contexto con un modelo que anota los mensajes que recibe.

    :param build_harness: Fabrica de aplicaciones de prueba.
    :type build_harness: callable
    :return: Contexto del escenario.
    :rtype: dict
    """
    model = RecordingModel("fake")
    return {"harness": build_harness(model=model), "model": model}


@given("the HR assistant is running with a recording tracer", target_fixture="ctx")
def assistant_with_recording_tracer(build_harness):
    """Contexto con un trazador en memoria.

    :param build_harness: Fabrica de aplicaciones de prueba.
    :type build_harness: callable
    :return: Contexto del escenario.
    :rtype: dict
    """
    return {"harness": build_harness(tracer=RecordingTracer())}


@given(
    "the HR assistant is running with a model that asks for an employee "
    "with an 81 character name",
    target_fixture="ctx",
)
def assistant_with_bad_args_model(build_harness):
    """Contexto con un modelo que pide ``get_employee`` con 81 caracteres.

    :param build_harness: Fabrica de aplicaciones de prueba.
    :type build_harness: callable
    :return: Contexto del escenario.
    :rtype: dict
    """
    model = BadArgsModel(requests=[("get_employee", {"employee_id": LONG_NAME})])
    return {"harness": build_harness(model=model)}


@given(
    "the HR assistant is running with a model that leaks an API key",
    target_fixture="ctx",
)
def assistant_with_leaking_model(build_harness):
    """Contexto con un modelo que responde con ``TEST_KEY``.

    :param build_harness: Fabrica de aplicaciones de prueba.
    :type build_harness: callable
    :return: Contexto del escenario.
    :rtype: dict
    """
    return {"harness": build_harness(model=SecretLeakingModel())}


# -- When -----------------------------------------------------------

@when(parsers.re(r'I ask "(?P<question>[^"]+)" after saying "(?P<earlier>[^"]+)"'))
def ask_with_history(ctx, question, earlier):
    """Pregunta con un historial de dos mensajes.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param question: Pregunta actual.
    :type question: str
    :param earlier: Mensaje anterior del usuario.
    :type earlier: str
    """
    history = [
        {"role": "user", "content": earlier},
        {"role": "assistant", "content": "De acuerdo."},
    ]
    ctx["response"] = ctx["harness"].client.post(
        "/ask", json={"question": question, "history": history}
    )


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
    assert ctx["response"].status_code == code


@then(parsers.parse('the redactions contain "{kind}"'))
def redactions_contain(ctx, kind):
    """Verifica que ``redactions`` incluya el tipo, sin repetir.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param kind: Tipo esperado, por ejemplo ``email``.
    :type kind: str
    """
    redactions = ctx["response"].json()["redactions"]
    assert kind in redactions
    assert len(redactions) == len(set(redactions))


@then("the redactions are empty")
def redactions_are_empty(ctx):
    """Verifica que no se oculto nada.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    """
    assert ctx["response"].json()["redactions"] == []


@then('the model received "[REDACTED:email]" and never the email, also in the history')
def model_received_clean_text(ctx):
    """Verifica que el modelo vio la marca y nunca el correo.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    """
    calls = ctx["model"].calls
    assert calls
    for messages in calls:
        assert all(EMAIL not in m["content"] for m in messages)
    first_call = calls[0]
    history_message, question_message = first_call[0], first_call[-1]
    assert "[REDACTED:email]" in history_message["content"]
    assert "[REDACTED:email]" in question_message["content"]


@then(parsers.parse('neither the log nor the trace contain "{value}"'))
def value_not_in_log_or_trace(ctx, value):
    """Verifica que el valor no aparezca en el log ni en la traza.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param value: Texto que nunca debe escribirse.
    :type value: str
    """
    harness = ctx["harness"]
    assert harness.log_text()
    assert harness.tracer.spans
    assert value not in harness.log_text()
    assert value not in harness.tracer.text()


@then(
    parsers.parse(
        'there is a security event with stage "{stage}", control "{control}" '
        'and kinds "{kind}"'
    )
)
def security_event_exists(ctx, stage, control, kind):
    """Verifica el evento ``security`` en el log y su span en la traza.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param stage: ``input`` u ``output``.
    :type stage: str
    :param control: Control que detecto algo.
    :type control: str
    :param kind: Tipo esperado en ``kinds``.
    :type kind: str
    """
    harness = ctx["harness"]
    request_id = ctx["response"].json()["request_id"]
    events = [
        e
        for e in harness.events("security")
        if e["stage"] == stage and e["control"] == control
    ]
    assert len(events) == 1
    assert events[0]["request_id"] == request_id
    assert events[0]["client"] == "tester"
    assert events[0]["kinds"] == [kind]
    spans = [
        s
        for s in harness.tracer.named("security")
        if s["metadata"].get("control") == control
    ]
    assert len(spans) == 1
    assert spans[0]["metadata"]["request_id"] == request_id


@then(parsers.parse('the metrics count {count:d} security event for "{control}"'))
def metrics_count_security(ctx, count, control):
    """Verifica el conteo de ``security`` en ``GET /metrics``.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param count: Conteo esperado.
    :type count: int
    :param control: Control a revisar.
    :type control: str
    """
    snapshot = ctx["harness"].client.get("/metrics").json()
    assert snapshot["security"][control] == count


@then(parsers.parse('the answer mentions "{text}"'))
def answer_mentions(ctx, text):
    """Verifica que la respuesta incluya un texto.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param text: Texto esperado.
    :type text: str
    """
    assert text in ctx["response"].json()["answer"]


@then('the answer contains "[REDACTED:secret]" and not the key')
def answer_hides_the_key(ctx):
    """Verifica que la clave no salga en la respuesta.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    """
    response = ctx["response"]
    assert "[REDACTED:secret]" in response.json()["answer"]
    assert TEST_KEY not in response.text
