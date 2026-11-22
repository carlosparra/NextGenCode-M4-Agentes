"""Step definitions for features/production.feature."""

from datetime import timedelta

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from conftest import ANA_KEY, BOB_KEY, log_lines

scenarios("features/production.feature")

KEYS = {"ana": ANA_KEY, "bob": BOB_KEY}
SAFE_PRODUCTION = {
    "ENVIRONMENT": "production",
    "MODEL_PROVIDER": "gateway",
    "CF_ACCOUNT_ID": "acct",
    "CF_API_TOKEN": "cloudflare-token-value",
    "API_KEYS": f"ana:{ANA_KEY}",
}


@pytest.fixture(name="world")
def world_fixture():
    """Bolsa mutable con la preparación, las respuestas y el resultado del arranque.

    :return: Diccionario del escenario.
    :rtype: dict
    """
    return {"env": {}, "client": None, "stream": None, "clock": None,
            "responses": [], "error": None, "key": None}


def _client(world, make_secure_client):
    """Build the client once, with the setup gathered so far."""
    if world["client"] is None:
        world["client"], world["stream"], world["clock"] = make_secure_client(
            env=world["env"]
        )
    return world["client"]


def _ask(world, make_secure_client, name, question):
    client = _client(world, make_secure_client)
    response = client.post(
        "/ask", json={"question": question}, headers={"X-API-Key": KEYS[name]}
    )
    world["responses"].append(response)
    world["key"] = KEYS[name]


@given(parsers.parse('the app has the clients "{first}" and "{second}"'))
def _clients(world, first, second):
    world["clients"] = {first, second}
    assert world["clients"] == set(KEYS)


@given(parsers.parse("the limit is {limit:d} requests per minute"))
def _limit(world, limit):
    world["env"]["RATE_LIMIT_PER_MINUTE"] = str(limit)


@given("the production setup uses the fake model")
def _prod_fake(world):
    world["env"] = {**SAFE_PRODUCTION, "MODEL_PROVIDER": "fake"}


@given("the production setup has no API keys")
def _prod_no_keys(world):
    world["env"] = {**SAFE_PRODUCTION, "API_KEYS": ""}


@given(parsers.parse('the production setup has a key of 15 characters for "{name}"'))
def _prod_short_key(world, name):
    world["key"] = "k" * 15
    world["env"] = {**SAFE_PRODUCTION, "API_KEYS": f"{name}:{world['key']}"}


@given("the production setup has tracing on and HIDE_INPUTS false")
def _prod_traces(world):
    world["env"] = {**SAFE_PRODUCTION, "LANGSMITH_TRACING": "true",
                    "HIDE_INPUTS": "false"}


@given("the production setup is correct")
def _prod_ok(world):
    world["env"] = dict(SAFE_PRODUCTION)


@given(parsers.parse('the key list is "{raw}"'))
def _key_list(world, raw):
    world["env"] = {"API_KEYS": raw}
    world["key"] = "secret-value-12345678"


@when(parsers.parse('a request to "{path}" has no key'))
def _no_key(world, make_secure_client, path):
    client = _client(world, make_secure_client)
    if path == "/ask":
        response = client.post("/ask", json={"question": "Who is EMP-0001?"})
    else:
        response = client.get(path)
    world["responses"].append(response)


@when(parsers.parse('a request to "{path}" uses the key "{key}"'))
def _wrong_key(world, make_secure_client, path, key):
    client = _client(world, make_secure_client)
    world["responses"].append(client.get(path, headers={"X-API-Key": key}))


@when(parsers.parse('"{name}" asks "{question}"'))
def _asks_once(world, make_secure_client, name, question):
    _ask(world, make_secure_client, name, question)


@when(parsers.parse('"{name}" asks "{question}" {times:d} times'))
def _asks_many(world, make_secure_client, name, question, times):
    for _ in range(times):
        _ask(world, make_secure_client, name, question)


@when(parsers.parse("the clock advances {seconds:d} seconds"))
def _advance(world, seconds):
    world["clock"]._current += timedelta(seconds=seconds)  # pylint: disable=protected-access


@when("the app starts")
def _start(world, make_secure_client):
    try:
        _client(world, make_secure_client)
    except ValueError as error:
        world["error"] = str(error)


@then(parsers.parse("the status is {status:d}"))
def _status(world, status):
    assert world["responses"][-1].status_code == status


@then(parsers.parse("the last status is {status:d}"))
def _last_status(world, status):
    assert world["responses"][-1].status_code == status


@then(parsers.parse('the detail is "{detail}"'))
def _detail(world, detail):
    assert world["responses"][-1].json() == {"detail": detail}


@then("the Retry-After header is between 1 and 60")
def _retry_after(world):
    assert 1 <= int(world["responses"][-1].headers["Retry-After"]) <= 60


@then("the public paths answer 200 without a key")
def _public(world, make_secure_client):
    client = _client(world, make_secure_client)
    for path in ("/", "/health", "/docs"):
        assert client.get(path).status_code == 200, path


@then(
    parsers.parse('the request, audit and agent_run events carry the client "{name}"')
)
def _client_in_log(world, name):
    events = log_lines(world["stream"])
    for event in ("request", "audit", "agent_run"):
        found = [line for line in events if line["event"] == event]
        assert found, event
        assert all(line["client"] == name for line in found), event


@then(
    parsers.parse(
        'the key of "{name}" is not in the log, the metrics or an error body'
    )
)
def _key_hidden(world, make_secure_client, name):
    client = _client(world, make_secure_client)
    key = KEYS[name]
    metrics = client.get("/metrics", headers={"X-API-Key": key}).text
    denied = client.post(
        "/ask", json={"question": "x"}, headers={"X-API-Key": key + "!"}
    )
    assert key not in world["stream"].getvalue()
    assert key not in metrics
    assert key not in denied.text


@then(parsers.parse('the start is refused mentioning "{text}"'))
def _refused(world, text):
    assert world["error"] is not None
    assert text in world["error"]


@then("the refusal does not contain the key")
def _refusal_no_key(world):
    assert world["key"] not in world["error"]


@then(parsers.parse('the refusal does not contain "{secret}"'))
def _refusal_no_secret(world, secret):
    assert secret not in world["error"]


@then(parsers.parse("the refusal mentions the length {length:d}"))
def _refusal_length(world, length):
    assert str(length) in world["error"]


@then("the app is running")
def _running(world):
    assert world["error"] is None
    assert world["client"].get("/health").status_code == 200
