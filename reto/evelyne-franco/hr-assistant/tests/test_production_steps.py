"""Pasos pytest-bdd para los escenarios de produccion.

Cubre ``spec/04-production.md``: una clave por cliente (401), el limite
de peticiones por cliente (429 con ``Retry-After``) con el reloj falso,
y las reglas de compliance que impiden arrancar en produccion.
"""

import io

from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, scenarios, then, when

from app.compliance import ComplianceError
from app.config import load_settings
from app.directory import Directory
from app.llm import FakeModel
from app.logs import JsonLogger
from app.main import create_app
from app.metrics import Metrics
from app.pricing import PriceTable
from tests.conftest import KEYS_BY_CLIENT, SLO_P95_MS, FakeClock

scenarios("features/production.feature")

QUESTION = "¿Quién es EMP-0004?"
NO_KEY = "none"
PRODUCTION_KEY = "acme-key-0123456789abcdef"
CF_TOKEN = "cf-token-do-not-leak"
PRODUCTION_ENV = {
    "ENVIRONMENT": "production",
    "MODEL_PROVIDER": "gateway",
    "CF_ACCOUNT_ID": "acc-123",
    "CF_GATEWAY_ID": "gw-456",
    "CF_API_TOKEN": CF_TOKEN,
    "API_KEYS": f"acme:{PRODUCTION_KEY}",
}
SHORT_KEY = "short-secret"
# Cada problema cambia una sola cosa de la configuracion correcta.
PROBLEMS = {
    "nothing wrong": {},
    "the fake model": {"MODEL_PROVIDER": "fake"},
    "no API keys": {"API_KEYS": ""},
    "a key shorter than 16 characters": {"API_KEYS": f"acme:{SHORT_KEY}"},
    "traces that show the inputs": {
        "LANGSMITH_TRACING": "true",
        "HIDE_INPUTS": "false",
    },
}


# -- Given ----------------------------------------------------------

@given("the HR assistant is running with API keys", target_fixture="ctx")
def assistant_with_keys(harness):
    """Contexto con la aplicacion estandar y sus dos clientes de prueba.

    :param harness: Arnes con cliente, log y metricas.
    :type harness: conftest.Harness
    :return: Contexto del escenario.
    :rtype: dict
    """
    return {"harness": harness, "response": None, "sent_key": None}


@given(
    parsers.parse("the HR assistant is running with a limit of {limit:d} "
                  "requests per minute"),
    target_fixture="ctx",
)
def assistant_with_limit(build_harness, limit):
    """Contexto con ``RATE_LIMIT_PER_MINUTE`` igual a ``limit``.

    :param build_harness: Fabrica de aplicaciones de prueba.
    :type build_harness: callable
    :param limit: Peticiones por cliente por minuto.
    :type limit: int
    :return: Contexto del escenario.
    :rtype: dict
    """
    return {"harness": build_harness(rate_limit=limit), "response": None}


@given(
    parsers.parse("a production configuration with {problem}"),
    target_fixture="ctx",
)
def production_configuration(problem):
    """Contexto con un entorno de produccion y un solo problema.

    :param problem: Nombre del problema, una llave de ``PROBLEMS``.
    :type problem: str
    :return: Contexto del escenario.
    :rtype: dict
    """
    return {"environ": {**PRODUCTION_ENV, **PROBLEMS[problem]}}


# -- When -----------------------------------------------------------

@when(parsers.parse('I call {method} "{path}" with the key "{key}"'))
def call_with_key(ctx, method, path, key):
    """Llama a la ruta sin clave (``none``) o con la clave indicada.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param method: ``GET`` o ``POST``.
    :type method: str
    :param path: Ruta de la peticion.
    :type path: str
    :param key: Clave que se manda, o ``none`` para no mandar ninguna.
    :type key: str
    """
    headers = {} if key == NO_KEY else {"X-API-Key": key}
    ctx["sent_key"] = None if key == NO_KEY else key
    anonymous = ctx["harness"].anonymous
    if method == "POST":
        response = anonymous.post(path, json={"question": QUESTION}, headers=headers)
    else:
        response = anonymous.get(path, headers=headers)
    ctx["response"] = response


@when(parsers.parse('client "{name}" asks "{question}"'))
def client_asks(ctx, name, question):
    """El cliente ``name`` hace una pregunta con su clave.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param name: Cliente de prueba.
    :type name: str
    :param question: Texto de la pregunta.
    :type question: str
    """
    ctx["sent_key"] = KEYS_BY_CLIENT[name]
    ctx["response"] = ctx["harness"].post_as(
        name, "/ask", json={"question": question}
    )


@when(parsers.parse('client "{name}" asks {count:d} times'))
def client_asks_many_times(ctx, name, count):
    """El cliente ``name`` hace ``count`` preguntas seguidas.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param name: Cliente de prueba.
    :type name: str
    :param count: Numero de preguntas.
    :type count: int
    """
    for _ in range(count):
        ctx["response"] = ctx["harness"].post_as(
            name, "/ask", json={"question": QUESTION}
        )


@when("one minute passes")
def one_minute_passes(ctx):
    """Adelanta el reloj falso 60 segundos.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    """
    ctx["harness"].clock.advance(60)


@when('I open "/", "/health" and "/docs" without a key')
def open_public_pages(ctx):
    """Abre las tres rutas publicas sin clave.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    """
    anonymous = ctx["harness"].anonymous
    ctx["responses"] = [anonymous.get(path) for path in ("/", "/health", "/docs")]


@when("the HR assistant starts")
def assistant_starts(ctx, employees_file, prices_file):
    """Intenta crear la aplicacion con la configuracion del contexto.

    Guarda la aplicacion o la excepcion que impidio arrancar.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param employees_file: Ruta al JSON temporal de empleados.
    :type employees_file: pathlib.Path
    :param prices_file: Ruta al JSON temporal de precios.
    :type prices_file: pathlib.Path
    """
    ctx["app"], ctx["error"] = None, None
    try:
        settings = load_settings(ctx["environ"])
        directory = Directory(str(employees_file))
        clock = FakeClock()
        ctx["app"] = create_app(
            settings=settings,
            models={
                name: FakeModel(name=name, departments=directory.departments)
                for name in (settings.model_small, settings.model_large)
            },
            prices=PriceTable.from_file(
                str(prices_file), (settings.model_small, settings.model_large)
            ),
            directory=directory,
            clock=clock,
            logger=JsonLogger(stream=io.StringIO(), service="hr", clock=clock),
            metrics=Metrics(slo_p95_ms=SLO_P95_MS),
        )
    except (ComplianceError, ValueError) as exc:
        ctx["error"] = exc


# -- Then -----------------------------------------------------------

@then(parsers.parse("the response status is {code:d}"))
def check_status(ctx, code):
    """Verifica el codigo HTTP de la ultima respuesta.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param code: Codigo esperado.
    :type code: int
    """
    assert ctx["response"].status_code == code


@then("the body is exactly the invalid or missing key error")
def body_is_invalid_key(ctx):
    """Verifica el cuerpo exacto del 401.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    """
    assert ctx["response"].json() == {"detail": "invalid or missing API key"}


@then("the body is exactly the rate limit error")
def body_is_rate_limit(ctx):
    """Verifica el cuerpo exacto del 429.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    """
    assert ctx["response"].json() == {"detail": "rate limit exceeded"}


@then("the response says how many seconds to wait")
def response_has_retry_after(ctx):
    """Verifica que ``Retry-After`` sea un entero de segundos mayor que 0.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    """
    assert int(ctx["response"].headers["Retry-After"]) > 0


@then("the key that was sent appears nowhere in the log")
def key_not_in_log(ctx):
    """Verifica que ni la clave enviada ni las de prueba esten en el log.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    """
    log = ctx["harness"].log_text()
    assert log
    for key in [ctx["sent_key"], *KEYS_BY_CLIENT.values()]:
        if key:
            assert key not in log
            assert key not in ctx["response"].text


@then(parsers.parse('the request log and the agent run name the client "{name}"'))
def log_names_client(ctx, name):
    """Verifica ``client`` en el evento ``request`` y en ``agent_run``.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param name: Cliente esperado.
    :type name: str
    """
    harness = ctx["harness"]
    (request,) = harness.events("request")
    (run,) = harness.events("agent_run")
    assert request["client"] == name
    assert run["client"] == name


@then("every response status is 200")
def every_status_is_200(ctx):
    """Verifica que todas las rutas publicas respondan 200.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    """
    assert [r.status_code for r in ctx["responses"]] == [200, 200, 200]


@then("it refuses to start with a compliance error")
def refuses_to_start(ctx):
    """Verifica que la aplicacion no se creo por una regla de compliance.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    """
    assert ctx["app"] is None
    assert isinstance(ctx["error"], ComplianceError)


@then("the error shows no secret value")
def error_has_no_secret(ctx):
    """Verifica que el mensaje no muestre claves ni tokens.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    """
    message = str(ctx["error"])
    for secret in (PRODUCTION_KEY, SHORT_KEY, CF_TOKEN):
        assert secret not in message


@then(parsers.parse('it answers client "{name}" with status {code:d}'))
def answers_client(ctx, name, code):
    """Verifica que arranco y que acepta la clave configurada.

    :param ctx: Contexto del escenario.
    :type ctx: dict
    :param name: Cliente configurado en ``API_KEYS``.
    :type name: str
    :param code: Codigo esperado.
    :type code: int
    """
    assert ctx["error"] is None
    assert name == "acme"
    client = TestClient(ctx["app"], raise_server_exceptions=False)
    response = client.post(
        "/ask",
        json={"question": QUESTION},
        headers={"X-API-Key": PRODUCTION_KEY},
    )
    assert response.status_code == code
