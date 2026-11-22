"""Pasos de ``features/costs.feature``: enrutamiento, ventana, caché y costo."""

import io

import httpx
import pytest
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, scenarios, then, when

from app.config import load_settings
from app.directory import EmployeeDirectory
from app.main import create_app

scenarios("features/costs.feature")

HISTORY = [
    {"role": "user", "content": "¿Quién es EMP-0004?"},
    {"role": "assistant", "content": "Es una persona de Ventas."},
    {"role": "user", "content": "¿Y EMP-0001?"},
    {"role": "assistant", "content": "Trabaja en Finanzas."},
]


@pytest.fixture
def context(api_key):
    """Estado compartido entre los pasos de un escenario.

    :return: Entorno (con la clave de prueba), modelo o manejador del gateway,
        clave y respuestas recibidas
    :rtype: dict
    """
    return {
        "environ": {"API_KEYS": f"qa-tester:{api_key}"},
        "api_key": api_key,
        "model": None,
        "handler": None,
        "responses": [],
    }


def _client(context):
    """Arma (una sola vez por escenario) el cliente con lo que pidieron los pasos.

    :param context: Estado del escenario
    :type context: dict
    :return: Cliente de prueba
    :rtype: fastapi.testclient.TestClient
    """
    if "client" not in context:
        settings = load_settings(dict(context["environ"]))
        employees = EmployeeDirectory(settings.employees_path)
        dependencies = {}
        if context["handler"] is not None:
            from app.llm import build_models  # pylint: disable=import-outside-toplevel

            transport = httpx.MockTransport(context["handler"])
            http_client = httpx.Client(transport=transport)
            dependencies["models"] = build_models(
                settings, employees, http_client=http_client
            )
        elif context["model"] is not None:
            dependencies["model"] = context["model"]
        app = create_app(
            settings=settings,
            directory=employees,
            log_stream=io.StringIO(),
            **dependencies,
        )
        context["client"] = TestClient(
            app,
            raise_server_exceptions=False,
            headers={"X-API-Key": context["api_key"]},
        )
    return context["client"]


@given("the assistant runs with the default configuration")
def default_configuration():
    """Sin variables: valores por omisión y modelo simulado."""


@given(parsers.parse('the variable "{name}" is set to "{value}"'))
def set_variable(context, name, value):
    """Fija una variable de entorno del escenario."""
    context["environ"][name] = value


@given("a scripted model that answers directly")
def scripted_answer(context, scripted_model):
    """Inyecta un modelo guionado que responde en la primera vuelta."""
    context["model"] = scripted_model(['{"answer": "Está en Ventas."}'])


@given("the gateway answers from its cache")
def gateway_cache_hit(context, gateway_environ, gateway_reply):
    """Usa el gateway simulado y marca cada respuesta como HIT de caché."""
    context["environ"].update(gateway_environ)
    context["handler"] = lambda request: gateway_reply(
        '{"answer": "Hola"}', cache_status="HIT"
    )


@given("the gateway is failing")
def gateway_failing(context, gateway_environ):
    """Usa el gateway simulado y hace que siempre responda 500."""
    context["environ"].update(gateway_environ)
    context["handler"] = lambda request: httpx.Response(500, json={"error": "boom"})


@when(parsers.parse('I ask "{question}"'))
def ask(context, question):
    """Manda la pregunta sin historial."""
    response = _client(context).post("/ask", json={"question": question})
    context["responses"].append(response)


@when(parsers.parse('I ask "{question}" after a history of four messages'))
def ask_with_history(context, question):
    """Manda la pregunta con cuatro mensajes de historial."""
    response = _client(context).post(
        "/ask", json={"question": question, "history": HISTORY}
    )
    context["responses"].append(response)


def _last_body(context):
    """Devuelve el cuerpo de la última respuesta, que debe ser 200.

    :param context: Estado del escenario
    :type context: dict
    :return: Cuerpo JSON
    :rtype: dict
    """
    response = context["responses"][-1]
    assert response.status_code == 200, response.text
    return response.json()


@then(parsers.parse('the answer comes from the model "{model}"'))
def answer_model(context, model):
    """Comprueba el modelo que eligió el enrutador."""
    assert _last_body(context)["model"] == model


@then(parsers.parse('the route is "{route}"'))
def answer_route(context, route):
    """Comprueba el motivo del enrutador."""
    assert _last_body(context)["route"] == route


@then("the answer cost is greater than zero")
def cost_positive(context):
    """El modelo simulado también tiene precio."""
    assert _last_body(context)["cost_usd"] > 0


@then("the answer cost is zero")
def cost_zero(context):
    """Una llamada cacheada no cuesta."""
    assert _last_body(context)["cost_usd"] == 0


@then(parsers.parse("the answer reports {count:d} cached call"))
def cached_calls(context, count):
    """Comprueba cuántas llamadas vinieron de la caché."""
    assert _last_body(context)["cached_calls"] == count


@then(parsers.parse("the model receives only the last {count:d} history messages"))
def history_window(context, count):
    """Entre el mensaje de sistema y la pregunta solo van los últimos mensajes."""
    _last_body(context)
    sent = context["model"].calls[0]
    assert sent[0]["role"] == "system"
    assert sent[-1]["content"] == "¿Y su departamento?"
    assert sent[1:-1] == HISTORY[-count:]


@then(parsers.parse("the response status is {status:d}"))
def response_status(context, status):
    """Comprueba el código HTTP."""
    assert context["responses"][-1].status_code == status


@then(parsers.parse('the error says "{detail}" with the request id'))
def error_detail(context, detail):
    """El error trae el detalle y el mismo ``request_id`` del encabezado."""
    response = context["responses"][-1]
    body = response.json()
    assert body["detail"] == detail
    assert body["request_id"]
    assert body["request_id"] == response.headers["X-Request-ID"]


@then("the metrics cost is the sum of both answers")
def metrics_cost(context):
    """``/metrics`` acumula el costo de todas las respuestas."""
    costs = [response.json()["cost_usd"] for response in context["responses"]]
    assert all(cost > 0 for cost in costs)
    metrics = _client(context).get("/metrics").json()
    assert metrics["cost_usd"] == pytest.approx(sum(costs))
