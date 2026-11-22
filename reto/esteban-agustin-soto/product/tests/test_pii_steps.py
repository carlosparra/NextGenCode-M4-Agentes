"""Step definitions for features/pii.feature (fictitious data only)."""

import json

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from conftest import ANA_KEY, ScriptedModel, answer_json, log_lines, tool_call

scenarios("features/pii.feature")

CURP = "AAAA010101HDFBBB09"
EMAIL = "persona.prueba@example.com"
SAFE_PRODUCTION = {
    "API_KEYS": f"ana:{ANA_KEY}", "ENVIRONMENT": "production",
    "MODEL_PROVIDER": "gateway", "CF_ACCOUNT_ID": "acct",
    "CF_API_TOKEN": "token-value-1",
}
ALLOWED_AUDIT_KEYS = {
    "ts", "service", "event", "request_id", "client", "action", "where",
    "curp", "email",
}


def _fill(text):
    """Reemplaza los marcadores ``<CURP>`` y ``<EMAIL>`` por los datos de prueba.

    :param text: Texto del escenario.
    :type text: str
    :return: Texto con los datos ficticios.
    :rtype: str
    """
    return text.replace("<CURP>", CURP).replace("<EMAIL>", EMAIL)


@pytest.fixture(name="world")
def world_fixture():
    """Bolsa mutable con el modelo, la respuesta, la bitácora y el arranque.

    :return: Diccionario del escenario.
    :rtype: dict
    """
    return {"model": None, "env": {}, "response": None, "stream": None,
            "error": None, "client": None}


def _ask(world, make_observed_client, question, history=None):
    """Envía la pregunta con el modelo y la configuración del escenario."""
    client, world["stream"] = make_observed_client(
        model=world["model"], env=world["env"]
    )
    body = {"question": _fill(question)}
    if history is not None:
        body["history"] = history
    world["response"] = client.post("/ask", json=body)


def _model_text(world):
    """Junta todo lo que el modelo simulado recibió, como un solo texto."""
    assert world["model"].calls
    return json.dumps(world["model"].calls, ensure_ascii=False)


def _has_pii(text):
    """Dice si el texto trae la CURP (en cualquier caja) o el correo."""
    return CURP in text or CURP.lower() in text or EMAIL in text


@given(parsers.parse('a scripted model that answers "{text}"'))
def _model_answers(world, text):
    world["model"] = ScriptedModel([answer_json(text)])


@given("a scripted model that answers with the CURP and the email")
def _model_invents(world):
    world["model"] = ScriptedModel([answer_json(f"Your data is {CURP} and {EMAIL}")])


@given("a scripted model that answers with the email")
def _model_email(world):
    world["model"] = ScriptedModel([answer_json(f"Write to {EMAIL}")])


@given(
    "a scripted model that asks for the email as employee id "
    "and the CURP as department"
)
def _model_tools(world):
    world["env"]["AGENT_MAX_STEPS"] = "5"
    world["model"] = ScriptedModel([
        tool_call("get_employee", employee_id=EMAIL),
        tool_call("search_by_department", department=CURP),
        answer_json("Done."),
    ])


@given("the production setup has PII_MASKING false")
def _prod_off(world):
    world["env"] = {**SAFE_PRODUCTION, "PII_MASKING": "false"}


@given("the production setup does not set PII_MASKING")
def _prod_default(world):
    world["env"] = dict(SAFE_PRODUCTION)


@when(parsers.parse('I ask the question "{question}"'))
def _ask_plain(world, make_observed_client, question):
    _ask(world, make_observed_client, question)


@when(parsers.parse(
    'I ask the question "{question}" with the CURP in a user message '
    "and the email in an assistant message"
))
def _ask_history(world, make_observed_client, question):
    history = [
        {"role": "user", "content": f"My CURP is {CURP}"},
        {"role": "assistant", "content": f"I noted {EMAIL}"},
    ]
    _ask(world, make_observed_client, question, history)


@when(parsers.parse(
    'I ask the question "{question}" with the email in a user message '
    "and in an assistant message"
))
def _ask_history_emails(world, make_observed_client, question):
    history = [
        {"role": "user", "content": f"Mail me at {EMAIL}"},
        {"role": "assistant", "content": f"I will write to {EMAIL}"},
    ]
    _ask(world, make_observed_client, question, history)


@when("the app starts")
def _start(world, make_secure_client):
    try:
        make_secure_client(env=world["env"])
    except ValueError as error:
        world["error"] = str(error)
    else:
        world["client"] = True


@then(parsers.parse("the response status is {status:d}"))
def _status(world, status):
    assert world["response"].status_code == status


@then("the model never receives the CURP or the email")
def _model_blind(world):
    assert not _has_pii(_model_text(world))


@then(parsers.parse('the model receives the markers "{first}" and "{second}"'))
def _model_markers(world, first, second):
    text = _model_text(world)
    assert first in text
    assert second in text


@then(parsers.parse('the answer is "{text}"'))
def _answer(world, text):
    assert world["response"].json()["answer"] == text


@then("the log has no CURP and no email")
def _log_clean(world):
    assert world["stream"].getvalue()
    assert not _has_pii(world["stream"].getvalue())


@then(parsers.parse(
    'the tool audit events show the arguments "{first}" and "{second}"'
))
def _tool_audit(world, first, second):
    calls = [line for line in log_lines(world["stream"])
             if line["event"] == "audit" and line["action"] == "tool_call"]
    assert [list(line["args"].values()) for line in calls] == [[first], [second]]


def _masked_events(world):
    """Devuelve los eventos ``audit`` con ``action=pii_masked``."""
    return [line for line in log_lines(world["stream"])
            if line["event"] == "audit" and line.get("action") == "pii_masked"]


@then(parsers.parse("there are exactly {count:d} pii_masked events"))
def _event_count(world, count):
    assert len(_masked_events(world)) == count


@then(parsers.parse(
    'the pii_masked event for "{where}" counts {curp:d} CURP and {email:d} email'
))
def _event_counts(world, where, curp, email):
    found = [line for line in _masked_events(world) if line["where"] == where]
    assert len(found) == 1
    assert (found[0]["curp"], found[0]["email"]) == (curp, email)


@then("the pii_masked events carry no value")
def _event_no_value(world):
    for line in _masked_events(world):
        assert set(line) <= ALLOWED_AUDIT_KEYS


@then(parsers.parse('the start is refused mentioning "{text}"'))
def _refused(world, text):
    assert world["error"] is not None
    assert text in world["error"]


@then("the app is running")
def _running(world):
    assert world["error"] is None
    assert world["client"]
