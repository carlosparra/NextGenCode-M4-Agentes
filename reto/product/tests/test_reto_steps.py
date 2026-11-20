"""Pasos de los escenarios de features/reto.feature (spec/05-reto.md)."""

from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, scenarios, then, when

from conftest import API_KEY_HEADER, TEST_API_KEY
from app.main import create_app

scenarios("features/reto.feature")

KEY_HEADERS = {API_KEY_HEADER: TEST_API_KEY}


def build_app(make_settings, directory, clock, log_stream, **env):
    """App con los modelos simulados con nombre y un cliente HTTP sin clave.

    :param make_settings: Fabrica de configuracion
    :type make_settings: callable
    :param directory: Directorio de empleados
    :type directory: app.directory.EmployeeDirectory
    :param clock: Reloj falso
    :type clock: FakeClock
    :param log_stream: Buffer del log
    :type log_stream: io.StringIO
    :param env: Variables de entorno extra
    :type env: dict
    :return: Cliente HTTP de prueba (la clave se manda en cada paso)
    :rtype: TestClient
    """
    app = create_app(
        settings=make_settings(**env),
        directory=directory,
        clock=clock,
        log_stream=log_stream,
    )
    return TestClient(app)


@given(
    parsers.re(r'the product runs with PII_POLICY "(?P<policy>\w+)"'),
    target_fixture="client",
)
def product_with_pii_policy(make_settings, directory, clock, log_stream, policy):
    """Producto con la politica de datos sensibles indicada."""
    return build_app(make_settings, directory, clock, log_stream, PII_POLICY=policy)


@given("the product runs with default settings", target_fixture="client")
def product_with_defaults(make_settings, directory, clock, log_stream):
    """Producto con la configuracion por omision."""
    return build_app(make_settings, directory, clock, log_stream)


@given("the product runs with the response cache on", target_fixture="client")
def product_with_cache(make_settings, directory, clock, log_stream):
    """Producto con la cache de respuestas encendida."""
    return build_app(
        make_settings,
        directory,
        clock,
        log_stream,
        RESPONSE_CACHE_TTL_SECONDS="300",
    )


@when(
    parsers.re(
        r'I ask "(?P<question>[^"]*)" with the key after the message '
        r'"(?P<message>[^"]*)"'
    ),
    target_fixture="response",
)
def ask_with_history(client, question, message):
    """Pregunta con un mensaje previo en el historial."""
    body = {"question": question, "history": [{"role": "user", "content": message}]}
    return client.post("/ask", json=body, headers=KEY_HEADERS)


@when(
    parsers.re(r'I ask "(?P<question>[^"]*)" twice with the key'),
    target_fixture="responses",
)
def ask_twice(client, question):
    """Hace la misma pregunta dos veces."""
    return [
        client.post("/ask", json={"question": question}, headers=KEY_HEADERS).json()
        for _ in range(2)
    ]


@when(
    parsers.re(r'I ask "(?P<question>[^"]*)" with the key$'),
    target_fixture="response",
)
def ask_with_key(client, question):
    """Pregunta con la clave valida."""
    return client.post("/ask", json={"question": question}, headers=KEY_HEADERS)


@when(
    parsers.re(r'I ask "(?P<question>[^"]*)" without a key'),
    target_fixture="response",
)
def ask_without_key(client, question):
    """Pregunta sin encabezado ``X-API-Key``."""
    return client.post("/ask", json={"question": question})


@then(parsers.re(r"the response status is (?P<status>\d+)"))
def response_status_is(response, status):
    """Comprueba el codigo HTTP."""
    assert response.status_code == int(status)


@then(parsers.re(r'the error detail is "(?P<detail>[^"]+)"'))
def error_detail_is(response, detail):
    """El cuerpo del error es exactamente el de la especificacion."""
    assert response.json() == {"detail": detail}


@then(parsers.re(r'the answer contains "(?P<text>[^"]+)"'))
def answer_contains(response, text):
    """La respuesta incluye el texto."""
    assert text in response.json()["answer"]


@then(parsers.re(r'the answer does not contain "(?P<text>[^"]+)"'))
def answer_does_not_contain(response, text):
    """La respuesta no incluye el texto."""
    assert text not in response.json()["answer"]


@then(parsers.re(r'the reported personal data is "(?P<types>[^"]+)"'))
def reported_personal_data(response, types):
    """``pii_detected`` lista los tipos sin repetir y en orden alfabetico."""
    assert response.json()["pii_detected"] == types.split(", ")


@then(
    parsers.re(
        r'the first answer is a cache "(?P<first>\w+)" and the second a cache '
        r'"(?P<second>\w+)"'
    )
)
def cache_outcomes(responses, first, second):
    """La primera respuesta es ``miss`` y la segunda ``hit``."""
    assert [body["cache"] for body in responses] == [first, second]


@then("the second answer repeats the first without tokens or cost")
def second_answer_is_free(responses):
    """Con ``hit`` se repite la respuesta y tokens y costo valen 0."""
    first, second = responses
    for name in ("answer", "steps", "tools_used"):
        assert second[name] == first[name], name
    assert (second["input_tokens"], second["output_tokens"]) == (0, 0)
    assert second["cost_usd"] == 0
    assert first["cost_usd"] > 0


@then(
    parsers.re(
        r"the metrics count (?P<hits>\d+) cache hit and (?P<misses>\d+) cache miss"
    )
)
def metrics_count_cache(client, hits, misses):
    """``/metrics`` reporta los aciertos y fallos de la cache."""
    metrics = client.get("/metrics", headers=KEY_HEADERS).json()
    assert metrics["cache"] == {"hits": int(hits), "misses": int(misses)}
