"""Pasos de ``features/security.feature``: claves por cliente y límite por minuto."""

import secrets
from datetime import datetime, timedelta, timezone

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("features/security.feature")

START = datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc)


class ManualClock:
    """Reloj falso que solo avanza cuando la prueba lo pide.

    ``monotonic()`` y ``now()`` se mueven juntos, así el limitador puede usar
    cualquiera de los dos.
    """

    def __init__(self):
        self._seconds = 0.0

    def advance(self, seconds):
        """Mueve el reloj hacia adelante.

        :param seconds: Segundos que avanza
        :type seconds: float
        """
        self._seconds += seconds

    def now(self):
        """Devuelve la hora fija más los segundos avanzados, en UTC.

        :return: Hora actual del reloj falso
        :rtype: datetime.datetime
        """
        return START + timedelta(seconds=self._seconds)

    def monotonic(self):
        """Devuelve los segundos avanzados desde el origen.

        :return: Segundos acumulados
        :rtype: float
        """
        return self._seconds


@pytest.fixture
def clock():
    """Reloj manual del escenario.

    :return: Reloj en el segundo 0
    :rtype: ManualClock
    """
    return ManualClock()


@pytest.fixture
def keys():
    """Claves generadas al vuelo para cada cliente conocido.

    :return: Clave por nombre de cliente
    :rtype: dict[str, str]
    """
    return {"alice": secrets.token_urlsafe(24), "bob": secrets.token_urlsafe(24)}


@pytest.fixture
def wrong_key():
    """Clave que ningún cliente tiene.

    :return: Clave inválida
    :rtype: str
    """
    return "wrong-" + secrets.token_urlsafe(16)


@pytest.fixture
def responses():
    """Respuestas HTTP del escenario, en orden.

    :return: Lista vacía que llenan los pasos
    :rtype: list
    """
    return []


@pytest.fixture
def start_service(make_observed, clock):
    """Arranca la app observada con el reloj manual y sin clave en el cliente HTTP.

    :return: Función que recibe el entorno y devuelve el servicio
    :rtype: collections.abc.Callable
    """

    def start(environ):
        return make_observed(environ, clock=clock, api_key=None)

    return start


@pytest.fixture
def ask_as(service, responses, keys):
    """Hace preguntas con la clave de un cliente y guarda cada respuesta.

    Se evalúa después del paso Given, que es el que define ``service``.

    :return: Función que recibe el cliente y la pregunta
    :rtype: collections.abc.Callable
    """

    def ask(client, question):
        response = service.client.post(
            "/ask", json={"question": question}, headers={"X-API-Key": keys[client]}
        )
        responses.append(response)

    return ask


# --- Given ---------------------------------------------------------------


@given(
    parsers.parse(
        'the assistant knows the clients "{first}" and "{second}" with a limit '
        "of {limit:d} questions per minute"
    ),
    target_fixture="service",
)
def known_clients(start_service, keys, first, second, limit):
    """Arranca la app con dos clientes, el límite pedido y un cliente HTTP sin clave."""
    environ = {
        "API_KEYS": f"{first}:{keys[first]},{second}:{keys[second]}",
        "RATE_LIMIT_PER_MINUTE": str(limit),
    }
    return start_service(environ)


# --- When ----------------------------------------------------------------


@when(parsers.parse('I ask "{question}" without an API key'))
def ask_without_key(service, responses, question):
    """Pregunta sin el encabezado ``X-API-Key``."""
    responses.append(service.client.post("/ask", json={"question": question}))


@when(parsers.parse('I ask "{question}" with a wrong API key'))
def ask_with_wrong_key(service, responses, wrong_key, question):
    """Pregunta con una clave que no existe."""
    response = service.client.post(
        "/ask", json={"question": question}, headers={"X-API-Key": wrong_key}
    )
    responses.append(response)


@when(parsers.parse('"{client}" asks "{question}" {count:d} times'))
def client_asks_several_times(ask_as, client, question, count):
    """El cliente pregunta varias veces seguidas con su clave."""
    for _ in range(count):
        ask_as(client, question)


@when(parsers.parse('"{client}" asks "{question}"'))
def client_asks(ask_as, client, question):
    """El cliente pregunta una vez con su clave."""
    ask_as(client, question)


@when(parsers.parse("the clock moves forward {seconds:d} seconds"))
def clock_moves(clock, seconds):
    """Avanza el reloj inyectado."""
    clock.advance(seconds)


@when("I read the metrics without an API key")
def read_metrics_without_key(service, responses):
    """Lee ``GET /metrics`` sin clave."""
    responses.append(service.client.get("/metrics"))


@when(parsers.parse('"{client}" reads the metrics'))
def client_reads_metrics(service, responses, keys, client):
    """Lee ``GET /metrics`` con la clave del cliente."""
    responses.append(
        service.client.get("/metrics", headers={"X-API-Key": keys[client]})
    )


@when("I open the page, the health check and the docs without an API key")
def open_public_pages(service, responses):
    """Abre las rutas públicas sin clave."""
    for path in ("/", "/health", "/docs"):
        responses.append(service.client.get(path))


# --- Then ----------------------------------------------------------------


@then(parsers.parse("the response status is {status:d}"))
def response_status(responses, status):
    """Comprueba el código HTTP de la última respuesta."""
    assert responses[-1].status_code == status, responses[-1].text


@then("every response has status 200")
def every_response_ok(responses):
    """Comprueba que todas las respuestas salieron bien."""
    assert [response.status_code for response in responses] == [200] * len(
        responses
    )


@then(parsers.parse('the error detail is "{detail}"'))
def error_detail(responses, detail):
    """El cuerpo del error es exactamente el detalle pedido."""
    assert responses[-1].json() == {"detail": detail}


@then("the response has a request id")
def response_has_request_id(responses):
    """Hasta un ``401`` lleva ``X-Request-ID``."""
    assert responses[-1].headers.get("X-Request-ID")


@then(parsers.parse("the log has a request event with status {status:d}"))
def log_has_request_event(service, status):
    """El rechazo queda en el log como cualquier otra petición."""
    (request,) = service.events("request")
    assert request["status"] == status


@then("the log does not contain the wrong API key")
def log_without_wrong_key(service, responses, wrong_key):
    """La clave enviada no aparece ni en el log ni en la respuesta."""
    assert service.events("request")
    assert wrong_key not in service.log_text()
    assert wrong_key not in responses[-1].text


@then(
    parsers.parse(
        'the request, audit and agent_run events name the client "{client}"'
    )
)
def events_name_the_client(service, client):
    """Los tres eventos de la petición llevan el nombre del cliente."""
    for name in ("request", "audit", "agent_run"):
        events = service.events(name)
        assert events, name
        assert all(event["client"] == client for event in events), name


@then("the log never contains a client API key")
def log_without_client_keys(service, keys, responses):
    """Ninguna clave válida se escribe en el log ni vuelve en la respuesta."""
    for key in keys.values():
        assert key not in service.log_text()
        assert key not in responses[-1].text


@then(parsers.parse('the Retry-After header is "{seconds}"'))
def retry_after_header(responses, seconds):
    """El encabezado dice cuántos segundos faltan."""
    assert responses[-1].headers["Retry-After"] == seconds
