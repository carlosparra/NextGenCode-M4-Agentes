"""Pruebas del costo en la API, el log, la pagina y los archivos de configuracion."""

import json
from pathlib import Path

import httpx
import pytest
from conftest import (
    BASE_FIELDS,
    LARGE_MODEL,
    SMALL_MODEL,
    build_default_app,
    gateway_client,
    keyed_client,
    read_log,
)

PRODUCT_DIR = Path(__file__).resolve().parent.parent
COST_FIELDS = {"model", "route", "cached_calls", "cost_usd"}
QUESTION = "¿Quién es EMP-0004?"
UNAVAILABLE_MESSAGE = "El modelo no está disponible en este momento. Intenta de nuevo."


@pytest.fixture
def priced_client(make_settings, directory, clock, log_stream):
    """App con los modelos simulados que arma la propia aplicacion (con precio)."""
    app = build_default_app(make_settings, directory, clock, log_stream)
    return keyed_client(app)


def test_default_app_answer_reports_model_route_cached_calls_and_cost(
    priced_client,
):
    body = priced_client.post("/ask", json={"question": QUESTION}).json()

    assert set(body) == BASE_FIELDS | COST_FIELDS
    assert body["model"] == SMALL_MODEL
    assert body["cached_calls"] == 0


def test_injected_model_answer_omits_the_cost_fields(client):
    response = client.post("/ask", json={"question": QUESTION})

    assert response.status_code == 200
    assert set(response.json()) == BASE_FIELDS
    assert client.get("/metrics").json()["cost_usd"] == 0


def test_failed_gateway_call_adds_no_cost_to_the_metrics(
    make_settings, directory, clock, log_stream
):
    transport = httpx.MockTransport(lambda _request: httpx.Response(503))
    client = gateway_client(make_settings, directory, clock, log_stream, transport)

    response = client.post("/ask", json={"question": QUESTION})

    assert response.status_code == 502
    assert client.get("/metrics").json()["cost_usd"] == 0


def test_agent_run_log_has_model_route_and_cost_but_no_question_text(
    priced_client, log_stream
):
    question = "Compara a los empleados de Finanzas"
    body = priced_client.post("/ask", json={"question": question}).json()

    (run,) = [line for line in read_log(log_stream) if line["event"] == "agent_run"]
    assert (run["model"], run["route"]) == (LARGE_MODEL, "keyword:compara")
    assert run["cost_usd"] == pytest.approx(body["cost_usd"])
    assert question not in log_stream.getvalue()


def test_home_page_marks_the_cost_and_the_request_id_lines(client):
    page = client.get("/").text

    assert '"cost"' in page
    assert '"request-id"' in page
    assert "innerHTML" not in page


def test_home_page_shows_the_model_and_the_cost_in_dollars_with_six_decimals(
    client,
):
    page = client.get("/").text

    assert "Modelo: " in page
    assert "US$" in page
    assert "toFixed(6)" in page


def test_home_page_explains_an_unavailable_model_in_spanish(client):
    page = client.get("/").text

    assert "502" in page
    assert UNAVAILABLE_MESSAGE in page


def test_env_example_lists_every_cost_variable_without_secret_values():
    lines = (PRODUCT_DIR / ".env.example").read_text(encoding="utf-8").splitlines()
    settings_lines = [line for line in lines if line and not line.startswith("#")]
    values = dict(line.split("=", 1) for line in settings_lines)

    for variable in (
        "MODEL_PROVIDER",
        "CF_ACCOUNT_ID",
        "CF_GATEWAY_ID",
        "CF_API_TOKEN",
        "MODEL_SMALL",
        "MODEL_LARGE",
        "ROUTING",
        "ROUTER_MAX_CHARS",
        "HISTORY_WINDOW",
        "MODEL_MAX_TOKENS",
        "MODEL_TEMPERATURE",
        "CACHE_TTL_SECONDS",
        "PRICES_PATH",
    ):
        assert variable in values
    assert values["CF_API_TOKEN"] == ""


def test_shipped_price_table_prices_both_default_models():
    path = PRODUCT_DIR / "data" / "model_prices.json"
    models = json.loads(path.read_text(encoding="utf-8"))["models"]

    for name in (SMALL_MODEL, LARGE_MODEL):
        assert models[name]["input"] > 0
        assert models[name]["output"] > 0
