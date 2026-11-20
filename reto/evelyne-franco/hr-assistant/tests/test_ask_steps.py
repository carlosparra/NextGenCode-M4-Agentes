"""Pasos pytest-bdd para los escenarios del feature 'ask'.

Implementa cada paso Gherkin que describe el comportamiento
del endpoint POST /ask y sus distintos casos de uso.
"""

from pytest_bdd import scenarios, given, when, then, parsers

scenarios("features/ask.feature")

FALLBACK_MSG = (
    "No pude completar la respuesta. "
    "Intenta con una pregunta mas concreta."
)


# -- Given ----------------------------------------------------------

@given(
    "the HR assistant is running",
    target_fixture="ctx",
)
def hr_assistant_running(client):
    """Prepara el contexto con el cliente HTTP estandar.

    :param client: Cliente de prueba inyectado por conftest.
    :type client: fastapi.testclient.TestClient
    :return: Diccionario mutable de contexto del escenario.
    :rtype: dict
    """
    return {"client": client, "response": None}


@given(
    "the HR assistant is running with max steps 1",
    target_fixture="ctx",
)
def hr_assistant_one_step(client_one_step):
    """Contexto con la aplicacion limitada a 1 paso.

    :param client_one_step: Cliente con max_steps=1.
    :type client_one_step: fastapi.testclient.TestClient
    :return: Diccionario mutable de contexto del escenario.
    :rtype: dict
    """
    return {"client": client_one_step, "response": None}


# -- When ----------------------------------------------------------

@when(
    parsers.parse('I ask "{question}"'),
    target_fixture="ctx",
)
def ask_question(ctx, question):
    """Envia una pregunta al endpoint POST /ask.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param question: Texto de la pregunta.
    :type question: str
    :return: Contexto actualizado con la respuesta.
    :rtype: dict
    """
    ctx["response"] = ctx["client"].post(
        "/ask", json={"question": question}
    )
    return ctx


@when(
    "I send an empty question",
    target_fixture="ctx",
)
def ask_empty_question(ctx):
    """Envia una pregunta vacia al endpoint POST /ask.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :return: Contexto actualizado con la respuesta.
    :rtype: dict
    """
    ctx["response"] = ctx["client"].post(
        "/ask", json={"question": ""}
    )
    return ctx


@when(
    "I send a question longer than the limit",
    target_fixture="ctx",
)
def ask_too_long_question(ctx):
    """Envia una pregunta que excede MAX_QUESTION_CHARS.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :return: Contexto actualizado con la respuesta.
    :rtype: dict
    """
    ctx["response"] = ctx["client"].post(
        "/ask", json={"question": "a" * 2001}
    )
    return ctx


@when(
    parsers.parse(
        'I ask "{question}" without history'
    ),
    target_fixture="ctx",
)
def ask_without_history(ctx, question):
    """Envia una pregunta sin el campo history.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param question: Texto de la pregunta.
    :type question: str
    :return: Contexto actualizado con la respuesta.
    :rtype: dict
    """
    ctx["response"] = ctx["client"].post(
        "/ask", json={"question": question}
    )
    return ctx


@when(
    parsers.parse(
        'I ask the limited app "{question}"'
    ),
    target_fixture="ctx",
)
def ask_limited_app(ctx, question):
    """Envia una pregunta a la app con tope de 1 paso.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param question: Texto de la pregunta.
    :type question: str
    :return: Contexto actualizado con la respuesta.
    :rtype: dict
    """
    ctx["response"] = ctx["client"].post(
        "/ask", json={"question": question}
    )
    return ctx


# -- Then -----------------------------------------------------------

@then(parsers.parse("the response status is {code:d}"))
def check_status_code(ctx, code):
    """Verifica el codigo HTTP de la respuesta.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param code: Codigo de estado esperado.
    :type code: int
    """
    assert ctx["response"].status_code == code


@then(parsers.parse('the answer mentions "{text}"'))
def answer_mentions(ctx, text):
    """Verifica que la respuesta contiene el texto dado.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param text: Texto que debe aparecer en la respuesta.
    :type text: str
    """
    body = ctx["response"].json()
    assert text in body["answer"]


@then(parsers.parse('the tools used include "{tool}"'))
def tools_include(ctx, tool):
    """Verifica que la herramienta se uso durante el paso.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param tool: Nombre de la herramienta esperada.
    :type tool: str
    """
    body = ctx["response"].json()
    assert tool in body["tools_used"]


@then("the answer is not empty")
def answer_not_empty(ctx):
    """Verifica que la respuesta no esta vacia.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    """
    body = ctx["response"].json()
    assert len(body["answer"]) > 0


@then("the answer contains the help message")
def answer_has_help(ctx):
    """Verifica que la respuesta es el mensaje de ayuda.

    El modelo simulado devuelve un mensaje orientativo cuando
    la pregunta no contiene un id de empleado ni un departamento.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    """
    body = ctx["response"].json()
    assert "EMP-" in body["answer"] or "departamento" in body["answer"]


@then("the answer contains the fallback message")
def answer_has_fallback(ctx):
    """Verifica que se devuelve el mensaje de fallback.

    Este mensaje fijo aparece cuando el agente alcanza el tope
    de pasos sin obtener una respuesta del modelo.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    """
    body = ctx["response"].json()
    assert "No pude completar" in body["answer"]
