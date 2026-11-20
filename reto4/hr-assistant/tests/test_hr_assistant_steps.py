"""Pasos de pytest-bdd para los escenarios de ``tests/features``.

Un solo módulo de pasos carga todos los ``.feature`` para que los pasos
comunes (arrancar el asistente, revisar el estado HTTP) se definan una vez.
"""

import json
import os
import re
import uuid

import httpx
import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from conftest import (
    API_KEY_HEADER,
    LARGE_MODEL,
    PRODUCTION_ENV,
    PRODUCTION_KEY,
    SMALL_MODEL,
    AlwaysToolModel,
    FakeClock,
    ScriptedModel,
    gateway_response,
)

from app.config import ConfigError

scenarios("features")

QUOTED = r'"(?P<{name}>[^"]*)"'
REQUEST_ID_HEADER = "X-Request-ID"
METRICS_FIELDS = {
    "pid", "requests", "error_rate", "latency_ms", "tokens", "slo", "cost_usd",
}
SAMPLE_QUESTION = {"question": "¿Quién es EMP-0004?"}


def _client_key(name):
    """Devuelve la clave de prueba de un cliente del escenario.

    :param name: Nombre del cliente
    :type name: str
    :return: Clave de 16 caracteres o más
    :rtype: str
    """
    return f"{name}-key-0123456789abcdef"


def _log_lines(context):
    """Junta el log JSON capturado hasta ahora y lo devuelve como dicts.

    :param context: Estado del escenario, con ``capsys``
    :type context: dict
    :return: Líneas crudas y eventos ya leídos
    :rtype: tuple[list[str], list[dict]]
    """
    captured = context.setdefault("log", [])
    output = context["capsys"].readouterr().out
    captured.extend(line for line in output.splitlines() if line.startswith("{"))
    return captured, [json.loads(line) for line in captured]


class CrashingModel:
    """Modelo de prueba que truena con un mensaje que no debe salir en el log.

    :param message: Mensaje del error
    :type message: str
    """

    def __init__(self, message):
        self._message = message

    def complete(self, _messages):
        """Lanza ``RuntimeError`` sin importar la conversación.

        :param _messages: Conversación enviada por el agente; no se usa
        :type _messages: list[dict]
        :raises RuntimeError: Siempre
        """
        raise RuntimeError(self._message)


def _quoted(name):
    """Devuelve la expresión regular de un texto entre comillas con nombre.

    :param name: Nombre del grupo capturado
    :type name: str
    :return: Expresión regular del grupo
    :rtype: str
    """
    return QUOTED.format(name=name)


@pytest.fixture
def context(capsys):
    """Estado compartido entre los pasos de un escenario.

    Guarda ``capsys`` desde el primer paso para que el log JSON de la
    petición quede capturado antes de revisarlo.
    """
    return {"capsys": capsys}


# --- Given -----------------------------------------------------------------


@given("the HR assistant runs with the fake model")
def fake_assistant(context, build_client):
    """Arranca la API con la configuración por omisión y el modelo simulado."""
    context["client"] = build_client()


@given(
    parsers.parse(
        "the HR assistant runs with a model that always asks for a tool "
        "and {max_steps:d} steps"
    )
)
def capped_assistant(context, build_client, max_steps):
    """Arranca la API con un modelo que nunca responde y un tope de vueltas."""
    environ = {"AGENT_MAX_STEPS": str(max_steps)}
    context["client"] = build_client(environ, AlwaysToolModel())


@given("the HR assistant runs with a model that records the conversation")
def recording_assistant(context, build_client):
    """Arranca la API con un modelo que guarda los mensajes que recibe."""
    model = ScriptedModel([('{"answer": "Listo."}', 1, 1)])
    context["model"] = model
    context["client"] = build_client(None, model)


@given(
    parsers.re(
        "the HR assistant runs with the fake model and " + _quoted("name")
        + " set to " + _quoted("value")
    )
)
def configured_assistant(context, build_client, name, value):
    """Arranca la API con el modelo simulado y una variable cambiada."""
    context["client"] = build_client({name: value})


@given("the HR assistant runs behind a gateway that answers from its cache")
def cached_gateway_assistant(context, build_gateway_client):
    """Arranca la API con un gateway simulado que responde desde su caché."""

    def handler(_request):
        headers = {"cf-aig-cache-status": "HIT"}
        return gateway_response('{"answer": "Listo."}', 50, 20, headers)

    extra = {"CACHE_TTL_SECONDS": "300"}
    context["client"] = build_gateway_client(handler, extra)


@given("the HR assistant runs behind a gateway that is down")
def broken_gateway_assistant(context, build_gateway_client):
    """Arranca la API con un gateway simulado que siempre falla."""

    def handler(_request):
        return httpx.Response(503, json={"error": "unavailable"})

    context["client"] = build_gateway_client(handler)


@given(
    parsers.re(
        "the HR assistant runs behind a recording gateway with " + _quoted("name")
        + " set to " + _quoted("value")
    )
)
def recording_gateway_assistant(context, build_gateway_client, name, value):
    """Arranca la API con un gateway simulado que guarda cada petición.

    El gateway responde sin acierto de caché (``MISS``), así que la llamada
    se cobra.
    """
    context["gateway_requests"] = []

    def handler(request):
        context["gateway_requests"].append(request)
        headers = {"cf-aig-cache-status": "MISS"}
        return gateway_response('{"answer": "Listo."}', 50, 20, headers)

    context["client"] = build_gateway_client(handler, {name: value})


@given(
    parsers.re(
        "the HR assistant runs with a model that crashes with " + _quoted("message")
    )
)
def crashing_assistant(context, build_client, message):
    """Arranca la API con un modelo que siempre lanza un error inesperado."""
    context["client"] = build_client(None, CrashingModel(message))


# --- When ------------------------------------------------------------------


def _ask(context, payload):
    """Envía ``payload`` a ``POST /ask`` y guarda la petición y la respuesta."""
    context["payload"] = payload
    context["response"] = context["client"].post("/ask", json=payload)


@when(
    parsers.re(
        "I ask " + _quoted("question") + " after saying " + _quoted("previous")
    )
)
def ask_with_history(context, question, previous):
    """Pregunta enviando un mensaje anterior en el historial."""
    history = [{"role": "user", "content": previous}]
    _ask(context, {"question": question, "history": history})


@when(
    parsers.re(
        "I ask " + _quoted("question") + " with a history entry from "
        + _quoted("role")
    )
)
def ask_with_role(context, question, role):
    """Pregunta con una entrada de historial que usa el rol indicado."""
    history = [{"role": role, "content": "Mensaje previo"}]
    _ask(context, {"question": question, "history": history})


@when(
    parsers.re(
        "I ask " + _quoted("question") + r" after (?P<count>\d+) history messages"
    )
)
def ask_with_long_history(context, question, count):
    """Pregunta con un historial de ``count`` mensajes numerados."""
    roles = ("user", "assistant")
    history = [
        {"role": roles[index % 2], "content": f"Mensaje {index}"}
        for index in range(int(count))
    ]
    context["history"] = history
    _ask(context, {"question": question, "history": history})


@when(
    parsers.re(
        "I ask " + _quoted("first") + " and then " + _quoted("second")
    )
)
def ask_twice(context, first, second):
    """Hace dos preguntas y guarda el costo de cada respuesta."""
    context["costs"] = []
    for question in (first, second):
        _ask(context, {"question": question})
        context["costs"].append(context["response"].json()["cost_usd"])


@when(
    parsers.re(
        "I ask " + _quoted("question") + " with the request id "
        + _quoted("request_id")
    )
)
def ask_with_request_id(context, question, request_id):
    """Pregunta mandando el encabezado ``X-Request-ID``."""
    context["response"] = context["client"].post(
        "/ask",
        json={"question": question},
        headers={REQUEST_ID_HEADER: request_id},
    )


@when(parsers.re("I ask " + _quoted("question") + "$"))
def ask(context, question):
    """Pregunta sin historial."""
    _ask(context, {"question": question})


@when("I send an empty question")
def ask_empty(context):
    """Envía una pregunta vacía."""
    _ask(context, {"question": ""})


@when(parsers.parse("I send a question of {length:d} characters"))
def ask_long(context, length):
    """Envía una pregunta del largo indicado."""
    _ask(context, {"question": "a" * length})


@when(parsers.re("I open " + _quoted("path")))
def open_path(context, path):
    """Abre una ruta con ``GET``."""
    context["response"] = context["client"].get(path)


# --- Then ------------------------------------------------------------------


@then(parsers.parse("the response status is {status:d}"))
def response_status(context, status):
    """Revisa el código HTTP."""
    assert context["response"].status_code == status


@then(parsers.re("the answer contains " + _quoted("text")))
def answer_contains(context, text):
    """Revisa que la respuesta incluya un texto."""
    assert text in context["response"].json()["answer"]


@then(parsers.re("the answer is " + _quoted("text")))
def answer_is(context, text):
    """Revisa la respuesta exacta."""
    assert context["response"].json()["answer"] == text


@then(parsers.re("the tools used are " + _quoted("tools")))
def tools_used(context, tools):
    """Revisa la lista de herramientas usadas, separadas por comas."""
    expected = [tool.strip() for tool in tools.split(",")]
    assert context["response"].json()["tools_used"] == expected


@then("no tools were used")
def no_tools_used(context):
    """Revisa que el agente no usó herramientas."""
    assert context["response"].json()["tools_used"] == []


@then(parsers.parse("the agent took {steps:d} steps"))
def agent_steps(context, steps):
    """Revisa cuántas vueltas dio el agente."""
    assert context["response"].json()["steps"] == steps


@then(
    parsers.re(
        "the model received " + _quoted("first") + " before " + _quoted("second")
    )
)
def model_received_in_order(context, first, second):
    """Revisa el orden de los mensajes que recibió el modelo."""
    contents = [message["content"] for message in context["model"].calls[0]]
    assert contents.index(first) < contents.index(second)


@then(
    parsers.re(
        "the health status is " + _quoted("status") + " with the current process id"
    )
)
def health_status(context, status):
    """Revisa ``/health``: estado y id del proceso que atiende."""
    assert context["response"].json() == {"status": status, "pid": os.getpid()}


@then(parsers.re("the page has the test ids " + _quoted("test_ids")))
def page_has_test_ids(context, test_ids):
    """Revisa que la página tenga los ``data-testid`` indicados."""
    page = context["response"].text
    for test_id in test_ids.split(","):
        assert f'data-testid="{test_id.strip()}"' in page


@then(parsers.re("the page does not contain " + _quoted("text")))
def page_does_not_contain(context, text):
    """Revisa que la página no incluya un texto."""
    assert text not in context["response"].text


@then(parsers.re("the answer comes from the (?P<size>small|large) model"))
def answer_model(context, size):
    """Revisa qué modelo eligió el enrutador."""
    expected = SMALL_MODEL if size == "small" else LARGE_MODEL
    assert context["response"].json()["model"] == expected


@then(parsers.re("the route is " + _quoted("route")))
def answer_route(context, route):
    """Revisa el motivo del enrutador."""
    assert context["response"].json()["route"] == route


@then("the cost is greater than zero")
def cost_is_positive(context):
    """Revisa que la respuesta tenga costo."""
    assert context["response"].json()["cost_usd"] > 0


@then("the cost is zero")
def cost_is_zero(context):
    """Revisa que la respuesta no haya costado."""
    assert context["response"].json()["cost_usd"] == 0


@then(parsers.parse("the cached calls are {count:d}"))
def cached_calls(context, count):
    """Revisa cuántas llamadas salieron de la caché del gateway."""
    assert context["response"].json()["cached_calls"] == count


@then(
    parsers.parse(
        "the model received the last {window:d} history messages and the question"
    )
)
def model_received_window(context, window):
    """Revisa que al modelo solo llegue la ventana del historial."""
    expected = [message["content"] for message in context["history"][-window:]]
    contents = [message["content"] for message in context["model"].calls[0]]
    assert contents[:-1] == expected
    assert contents[-1] == context["payload"]["question"]


@then(parsers.re("the error is " + _quoted("detail") + " with a request id"))
def error_with_request_id(context, detail):
    """Revisa el cuerpo del error: detalle y ``request_id``."""
    body = context["response"].json()
    assert body["detail"] == detail
    assert body["request_id"]


@then("the metrics cost is the sum of both answers")
def metrics_cost(context):
    """Revisa que ``/metrics`` acumule el costo de las respuestas."""
    expected = sum(context["costs"])
    assert expected > 0
    assert context["response"].json()["cost_usd"] == pytest.approx(expected)


@then(
    parsers.re(
        "the gateway received the header " + _quoted("header")
        + " with " + _quoted("value")
    )
)
def gateway_received_header(context, header, value):
    """Revisa un encabezado de cada petición que recibió el gateway."""
    assert context["gateway_requests"]
    for request in context["gateway_requests"]:
        assert request.headers[header] == value


@then(
    parsers.re(
        "the gateway received " + _quoted("field") + r" equal to (?P<value>\d+)"
    )
)
def gateway_received_field(context, field, value):
    """Revisa un campo del cuerpo de cada petición que recibió el gateway."""
    assert context["gateway_requests"]
    for request in context["gateway_requests"]:
        assert json.loads(request.content)[field] == int(value)


@then("the response has a generated request id in the header and the body")
def generated_request_id(context):
    """Revisa que el id generado sea un UUID y viaje en encabezado y cuerpo."""
    response = context["response"]
    request_id = response.headers[REQUEST_ID_HEADER]
    uuid.UUID(request_id)
    assert response.json()["request_id"] == request_id


@then(
    parsers.re(
        "the request id is " + _quoted("request_id") + " in the header and the body"
    )
)
def kept_request_id(context, request_id):
    """Revisa que se conserve el id que mandó el cliente."""
    response = context["response"]
    assert response.headers[REQUEST_ID_HEADER] == request_id
    assert response.json()["request_id"] == request_id


@then("the metrics report requests, error rate, latency, tokens, SLO and cost")
def metrics_fields(context):
    """Revisa la forma de ``/metrics`` después de una pregunta."""
    body = context["response"].json()
    assert set(body) == METRICS_FIELDS
    assert body["requests"] >= 1
    assert set(body["latency_ms"]) == {"p50", "p95"}
    assert set(body["tokens"]) == {"input", "output"}
    assert set(body["slo"]) == {"p95_ms_target", "met"}
    assert body["cost_usd"] > 0


@then(
    parsers.re(
        "the " + _quoted("event") + " log line does not contain " + _quoted("text")
    )
)
def log_line_without_text(context, event, text):
    """Revisa que el evento exista en el log JSON y no incluya el texto."""
    output = context["capsys"].readouterr().out
    lines = [line for line in output.splitlines() if line.startswith("{")]
    matching = [line for line in lines if json.loads(line).get("event") == event]
    assert matching
    for line in matching:
        assert text not in line


# --- Sesión 4: clave por cliente --------------------------------------------


@given(
    "the HR assistant runs with the fake model for a caller without an API key"
)
def keyless_assistant(context, build_client):
    """Arranca la API con el modelo simulado y un cliente HTTP sin clave."""
    context["client"] = build_client(api_key=None)


@given(
    parsers.re(
        "the HR assistant runs with the fake model for a caller with the API key "
        + _quoted("key")
    )
)
def wrong_key_assistant(context, build_client, key):
    """Arranca la API con un cliente HTTP que manda una clave desconocida."""
    context["client"] = build_client(api_key=key)


@given(
    parsers.re(
        "the HR assistant runs for the client " + _quoted("name")
        + " with the API key " + _quoted("key")
    )
)
def single_client_assistant(context, build_client, name, key):
    """Arranca la API con un único cliente configurado en ``API_KEYS``."""
    context["client"] = build_client({"API_KEYS": f"{name}:{key}"}, api_key=key)


@then(parsers.re("the response body is exactly the error " + _quoted("detail")))
def exact_error_body(context, detail):
    """Revisa que el cuerpo del error sea exactamente ``{"detail": ...}``."""
    assert context["response"].json() == {"detail": detail}


@then(parsers.re("the page contains " + _quoted("text")))
def page_contains(context, text):
    """Revisa que la página incluya un texto."""
    assert text in context["response"].text


@then(parsers.re("the " + _quoted("test_id") + " field is a password field"))
def field_is_password(context, test_id):
    """Revisa que el campo con ese ``data-testid`` sea de tipo contraseña."""
    pattern = r"<input[^>]*data-testid=\"" + re.escape(test_id) + r"\"[^>]*>"
    tag = re.search(pattern, context["response"].text, re.DOTALL)
    assert tag is not None
    assert 'type="password"' in tag.group(0)


@then(parsers.re("the paths " + _quoted("paths") + r" answer (?P<status>\d+)"))
def paths_answer(context, paths, status):
    """Revisa que varias rutas respondan el código indicado."""
    for path in paths.split(","):
        assert context["client"].get(path.strip()).status_code == int(status)


@then(
    parsers.re(
        "the " + _quoted("event") + " log line names the client " + _quoted("name")
    )
)
def log_line_names_client(context, event, name):
    """Revisa que el evento del log lleve el campo ``client``."""
    _, events = _log_lines(context)
    matching = [entry for entry in events if entry.get("event") == event]
    assert matching
    assert all(entry.get("client") == name for entry in matching)


@then(parsers.re("no log line contains " + _quoted("text")))
def no_log_line_contains(context, text):
    """Revisa que ninguna línea del log incluya el texto."""
    lines, _ = _log_lines(context)
    assert lines
    assert all(text not in line for line in lines)


# --- Sesión 4: límite de peticiones -----------------------------------------


@given(
    parsers.parse(
        "the HR assistant runs with a limit of {limit:d} requests per minute "
        "and a fake clock"
    )
)
def limited_assistant(context, build_client, limit):
    """Arranca la API con un límite bajo y un reloj que no avanza solo."""
    context["clock"] = FakeClock()
    environ = {"RATE_LIMIT_PER_MINUTE": str(limit)}
    context["client"] = build_client(environ, clock=context["clock"])


@given(
    parsers.re(
        "the HR assistant runs for the clients " + _quoted("names")
        + r" with a limit of (?P<limit>\d+) requests? per minute"
    )
)
def multi_client_assistant(context, build_client, names, limit):
    """Arranca la API con varios clientes, un límite bajo y un reloj falso."""
    clients = [name.strip() for name in names.split(",")]
    api_keys = ",".join(f"{name}:{_client_key(name)}" for name in clients)
    environ = {"API_KEYS": api_keys, "RATE_LIMIT_PER_MINUTE": limit}
    context["client"] = build_client(environ, api_key=None, clock=FakeClock())
    context["by_client"] = {}


@when(parsers.parse("I send {count:d} questions"))
def send_questions(context, count):
    """Envía varias preguntas seguidas y guarda la última respuesta."""
    for _ in range(count):
        context["response"] = context["client"].post("/ask", json=SAMPLE_QUESTION)


@when(parsers.parse("the clock moves forward {seconds:d} seconds"))
def clock_moves(context, seconds):
    """Avanza el reloj falso sin dormir."""
    context["clock"].advance(seconds)


@when(
    parsers.re(
        "the client " + _quoted("name") + r" sends (?P<count>\d+) questions?"
    )
)
def client_sends_questions(context, name, count):
    """Envía preguntas con la clave de un cliente y guarda su última respuesta."""
    headers = {API_KEY_HEADER: _client_key(name)}
    for _ in range(int(count)):
        context["by_client"][name] = context["client"].post(
            "/ask", json=SAMPLE_QUESTION, headers=headers
        )


@then(parsers.parse("the response asks to retry after {seconds:d} seconds"))
def retry_after(context, seconds):
    """Revisa el encabezado ``Retry-After`` del ``429``."""
    assert context["response"].headers["Retry-After"] == str(seconds)


@then(
    parsers.re(
        "the last response for " + _quoted("name") + r" has status (?P<status>\d+)"
    )
)
def client_last_status(context, name, status):
    """Revisa el código de la última respuesta de un cliente."""
    assert context["by_client"][name].status_code == int(status)


# --- Sesión 4: compliance ---------------------------------------------------


@given("a production configuration that is otherwise valid")
def production_environ(context):
    """Prepara variables de producción que cumplen todas las reglas."""
    context["environ"] = dict(PRODUCTION_ENV)


@when(parsers.re(_quoted("name") + " is set to " + _quoted("value")))
def set_variable(context, name, value):
    """Cambia una variable de la configuración de producción."""
    context["environ"][name] = value


@when("the HR assistant starts")
def assistant_starts(context, build_client):
    """Intenta arrancar la API y guarda el error de configuración, si hay."""
    context["error"] = None
    try:
        context["client"] = build_client(
            context["environ"], api_key=PRODUCTION_KEY
        )
    except ConfigError as error:
        context["error"] = error


@then(parsers.re("startup fails mentioning " + _quoted("text")))
def startup_fails(context, text):
    """Revisa que el arranque falle con un mensaje que nombra la regla."""
    assert context["error"] is not None
    assert text in str(context["error"])


@then(parsers.re("the startup error does not reveal " + _quoted("secret")))
def startup_error_hides_secret(context, secret):
    """Revisa que el mensaje de arranque no incluya ninguna clave."""
    assert secret not in str(context["error"])


@then(
    parsers.re(
        "startup succeeds and " + _quoted("path") + r" answers (?P<status>\d+)"
    )
)
def startup_succeeds(context, path, status):
    """Revisa que el arranque funcione y la ruta pública responda."""
    assert context["error"] is None
    assert context["client"].get(path).status_code == int(status)


# --- Sesión 4: enmascarado de PII -------------------------------------------


def _model_conversation(context):
    """Devuelve como texto todo lo que recibió el modelo que graba.

    :param context: Estado del escenario, con ``model``
    :type context: dict
    :return: Las llamadas al modelo en JSON, sin escapar acentos
    :rtype: str
    """
    assert context["model"].calls
    return json.dumps(context["model"].calls, ensure_ascii=False)


def _counts_in(value):
    """Junta los diccionarios de conteos que haya dentro de un evento del log.

    :param value: Valor de un campo del evento
    :type value: object
    :return: Diccionarios ``tipo -> conteo`` encontrados
    :rtype: list[dict]
    """
    if not isinstance(value, dict):
        return []
    found = [value] if value and all(
        isinstance(count, int) for count in value.values()
    ) else []
    for nested in value.values():
        found.extend(_counts_in(nested))
    return found


@given(
    parsers.re(
        "the HR assistant runs with a model that answers " + _quoted("answer")
    )
)
def answering_assistant(context, build_client, answer):
    """Arranca la API con un modelo que siempre da la misma respuesta."""
    model = ScriptedModel([(json.dumps({"answer": answer}), 1, 1)])
    context["model"] = model
    context["client"] = build_client(None, model)


@then(parsers.re("the model never received " + _quoted("text")))
def model_never_received(context, text):
    """Revisa que el texto no aparezca en nada de lo que recibió el modelo."""
    assert text not in _model_conversation(context)


@then(parsers.re("the model received a message containing " + _quoted("text")))
def model_received_text(context, text):
    """Revisa que el texto aparezca en lo que recibió el modelo."""
    assert text in _model_conversation(context)


@then(
    parsers.re(r"the log records (?P<count>\d+) masked " + _quoted("kind"))
)
def log_records_masked_count(context, count, kind):
    """Revisa que algún evento del log cuente lo enmascarado de ese tipo.

    No depende del nombre del evento ni del campo: busca un diccionario de
    conteos ``tipo -> número`` en cualquier evento.
    """
    _, events = _log_lines(context)
    counts = [found for event in events for found in _counts_in(event)]
    assert any(found.get(kind) == int(count) for found in counts)
