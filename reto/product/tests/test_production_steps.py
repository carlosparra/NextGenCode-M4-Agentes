"""Pasos de los escenarios de features/production.feature."""

import httpx
import pytest
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, scenarios, then, when

from conftest import (
    API_KEY_HEADER,
    GATEWAY_ENV,
    TEST_API_KEY,
    TEST_API_KEYS,
    ManualClock,
    RecordingTracer,
    read_log,
)
from app.config import ConfigError
from app.main import create_app
from app.ratelimit import RateLimiter

scenarios("features/production.feature")

QUESTION = "¿Quién es EMP-0004?"
OTHER_KEY = "other-key-abcdefghijklmnop"
PRODUCTION_KEY = "p" * 20
SHORT_KEY = "k" * 15
SAFE_PRODUCTION_ENV = {
    **GATEWAY_ENV,
    "ENVIRONMENT": "production",
    "API_KEYS": f"prod:{PRODUCTION_KEY}",
}
UNSAFE_CHANGES = {
    "a safe configuration": {},
    "the fake model": {"MODEL_PROVIDER": "fake"},
    "no API keys": {"API_KEYS": ""},
    "a key of 15 characters": {"API_KEYS": f"prod:{SHORT_KEY}"},
    "traces on and outputs not hidden": {
        "LANGSMITH_TRACING": "true",
        "LANGSMITH_API_KEY": "lsv2-test-key",
        "HIDE_OUTPUTS": "false",
    },
}


@pytest.fixture
def manual_clock():
    """Reloj que solo avanza cuando el escenario lo pide."""
    return ManualClock()


@pytest.fixture
def tracer():
    """Trazador que guarda lo que recibe."""
    return RecordingTracer()


def build_app(make_settings, directory, manual_clock, log_stream, tracer, **env):
    """App con modelos simulados, reloj manual y limite de 2 por minuto."""
    app = create_app(
        settings=make_settings(**env),
        directory=directory,
        clock=manual_clock,
        log_stream=log_stream,
        tracer=tracer,
        rate_limiter=RateLimiter(2, manual_clock),
    )
    return TestClient(app)


def start_product(make_settings, directory, env):
    """Intenta arrancar la app; devuelve el cliente o el error de configuracion."""
    offline = httpx.MockTransport(lambda _request: httpx.Response(503))
    try:
        app = create_app(
            settings=make_settings(**env),
            directory=directory,
            http_client=httpx.Client(transport=offline),
        )
    except ConfigError as error:
        return {"error": error, "client": None}
    return {"error": None, "client": TestClient(app)}


@given(
    'the product runs with the client "tests" and a limit of 2 requests per minute',
    target_fixture="client",
)
def product_with_one_client(
    make_settings, directory, manual_clock, log_stream, tracer
):
    """Un solo cliente configurado: ``tests``."""
    return build_app(make_settings, directory, manual_clock, log_stream, tracer)


@given('a second client "other" with its own key', target_fixture="client")
def product_with_two_clients(
    make_settings, directory, manual_clock, log_stream, tracer
):
    """Dos clientes, cada uno con su propia cuenta de peticiones."""
    keys = f"{TEST_API_KEYS},other:{OTHER_KEY}"
    return build_app(
        make_settings, directory, manual_clock, log_stream, tracer, API_KEYS=keys
    )


@when(
    parsers.re(r'I ask "(?P<question>[^"]*)" without a key'),
    target_fixture="response",
)
def ask_without_key(client, question):
    """Pregunta sin encabezado ``X-API-Key``."""
    return client.post("/ask", json={"question": question})


@when(
    parsers.re(r'I ask "(?P<question>[^"]*)" with the key "(?P<key>[^"]*)"'),
    target_fixture="response",
)
def ask_with_key(client, question, key):
    """Pregunta con una clave dada."""
    headers = {API_KEY_HEADER: key}
    return client.post("/ask", json={"question": question}, headers=headers)


@when(
    parsers.re(r'I ask "(?P<question>[^"]*)" with the valid key'),
    target_fixture="response",
)
def ask_with_valid_key(client, question):
    """Pregunta con la clave del cliente ``tests``."""
    return ask_with_key(client, question, TEST_API_KEY)


@when(
    parsers.re(r'I ask "(?P<question>[^"]*)" as the client "other"'),
    target_fixture="response",
)
def ask_as_other(client, question):
    """Pregunta con la clave del segundo cliente."""
    return ask_with_key(client, question, OTHER_KEY)


@when(parsers.re(r"I ask (?P<count>\d+) questions with the valid key"))
def ask_many(client, count):
    """Gasta peticiones del cliente ``tests``."""
    for _ in range(int(count)):
        ask_with_key(client, QUESTION, TEST_API_KEY)


@when(parsers.re(r"(?P<seconds>\d+) seconds pass"))
def time_passes(manual_clock, seconds):
    """Avanza el reloj manual."""
    manual_clock.advance(int(seconds))


@when(
    parsers.re(r"the product starts in production with (?P<setting>.+)$"),
    target_fixture="startup",
)
def start_in_production(make_settings, directory, setting):
    """Arranca con la configuracion segura mas el cambio del escenario."""
    env = {**SAFE_PRODUCTION_ENV, **UNSAFE_CHANGES[setting]}
    return start_product(make_settings, directory, env)


@when(
    parsers.re(r'the product reads API_KEYS "(?P<raw>[^"]*)"'),
    target_fixture="startup",
)
def start_with_api_keys(make_settings, directory, raw):
    """Arranca en desarrollo con un ``API_KEYS`` dado."""
    return start_product(make_settings, directory, {"API_KEYS": raw})


@then(parsers.re(r"the response status is (?P<status>\d+)"))
def response_status_is(response, status):
    """Comprueba el codigo HTTP."""
    assert response.status_code == int(status)


@then(parsers.re(r'the error detail is "(?P<detail>[^"]+)"'))
def error_detail_is(response, detail):
    """El cuerpo del error es exactamente el de la especificacion."""
    assert response.json() == {"detail": detail}


@then(parsers.re(r'the header "(?P<name>[^"]+)" is "(?P<value>[^"]+)"'))
def header_is(response, name, value):
    """Comprueba un encabezado de la respuesta."""
    assert response.headers[name] == value


@then("the key never appears in the log or the traces")
def key_never_appears(log_stream, tracer):
    """La clave valida no se escribe en el log ni en las trazas."""
    text_never_appears(log_stream, tracer, TEST_API_KEY)


@then(
    parsers.re(r'the text "(?P<text>[^"]+)" never appears in the log or the traces')
)
def text_never_appears(log_stream, tracer, text):
    """Un texto dado no aparece en el log ni en las trazas."""
    assert text not in log_stream.getvalue()
    assert text not in repr(tracer.spans)


@then(parsers.re(r'the "request" event of the log has the client "(?P<name>[^"]+)"'))
def request_event_has_client(log_stream, name):
    """El evento ``request`` de ``/ask`` nombra al cliente."""
    events = [e for e in read_log(log_stream) if e["event"] == "request"]
    assert [e["client"] for e in events if e["path"] == "/ask"] == [name]


@then(parsers.re(r'the traces carry the client "(?P<name>[^"]+)"'))
def traces_carry_client(tracer, name):
    """La traza de la corrida del agente lleva el nombre del cliente."""
    runs = [span for span in tracer.spans if span.get("name") == "agent_run"]
    assert [span.get("client") for span in runs] == [name]


@then('"/", "/health" and "/docs" answer 200 without a key')
def public_pages_need_no_key(client):
    """Las paginas publicas responden sin clave."""
    for path in ("/", "/health", "/docs"):
        assert client.get(path).status_code == 200, path


@then('"/metrics" answers 401 without a key and 200 with the valid key')
def metrics_need_a_key(client):
    """``/metrics`` solo responde con clave."""
    assert client.get("/metrics").status_code == 401
    keyed = client.get("/metrics", headers={API_KEY_HEADER: TEST_API_KEY})
    assert keyed.status_code == 200


@then(parsers.re(r'it refuses to start with an error that names "(?P<text>[^"]+)"'))
def refuses_to_start(startup, text):
    """El arranque falla con ``ConfigError`` y el mensaje nombra la causa."""
    assert startup["error"] is not None
    assert text in str(startup["error"])


@then("the error never contains a key")
def error_has_no_key(startup):
    """Ninguna clave aparece en el mensaje de error."""
    message = str(startup["error"])
    assert PRODUCTION_KEY not in message
    assert SHORT_KEY not in message


@then(parsers.re(r"the error mentions the length (?P<length>\d+)"))
def error_mentions_length(startup, length):
    """El mensaje dice el largo de la entrada que falla."""
    assert length in str(startup["error"])


@then(parsers.re(r'the error does not contain "(?P<text>[^"]+)"'))
def error_does_not_contain(startup, text):
    """El valor de la entrada nunca se muestra."""
    assert text not in str(startup["error"])


@then('it starts and "/health" answers 200')
def starts_and_is_healthy(startup):
    """Con la configuracion segura el producto arranca."""
    assert startup["error"] is None
    assert startup["client"].get("/health").status_code == 200
