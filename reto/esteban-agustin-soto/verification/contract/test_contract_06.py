"""Contrato de la sesión 6: costo por petición en el log y documentación pública.

La prueba lee la salida del producto, guardada en un archivo, y la compara con
lo que devolvió la API.
"""

import json
import time

import httpx

WAIT_SECONDS = 3.0
PUBLIC_PATHS = ("/docs", "/openapi.json")
ROUTES = ("/", "/health", "/ask", "/metrics")
QUESTION = {"question": "¿Quién es EMP-0004?"}


def agent_run_for(log_path, request_id):
    """Espera y devuelve el evento ``agent_run`` de una petición, o ``None``."""
    deadline = time.monotonic() + WAIT_SECONDS
    while True:
        for line in log_path.read_text("utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("event") == "agent_run" and (
                event.get("request_id") == request_id
            ):
                return event
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.05)


def test_agent_run_carries_the_same_cost_as_the_response(api_logged):
    client, log_path = api_logged
    response = client.post("/ask", json=QUESTION)
    assert response.status_code == 200
    body = response.json()
    event = agent_run_for(log_path, body["request_id"])
    assert event is not None
    assert isinstance(event["cost_usd"], float)
    assert event["cost_usd"] == body["cost_usd"]


def test_the_response_keeps_its_ten_fields(api):
    body = api.post("/ask", json=QUESTION).json()
    assert set(body) == {
        "model", "route", "cached_calls", "cost_usd", "answer", "steps",
        "tools_used", "input_tokens", "output_tokens", "request_id",
    }


def test_the_documentation_is_public(api):
    for path in PUBLIC_PATHS:
        assert api.get(path).status_code == 200, path


def test_the_schema_describes_every_route_and_the_api_key(api):
    schema = api.get("/openapi.json").json()
    assert set(ROUTES) <= set(schema["paths"])
    schemes = schema["components"]["securitySchemes"].values()
    assert any(
        item["type"] == "apiKey" and item["name"] == "X-API-Key"
        and item["in"] == "header"
        for item in schemes
    )


def test_documenting_does_not_change_the_unauthorized_answer(api):
    # Sin cliente de la fábrica: no manda la clave
    for method, path in (("post", "/ask"), ("get", "/metrics")):
        kwargs = {"json": QUESTION} if method == "post" else {}
        response = httpx.request(method, f"{api.base_url}{path}", **kwargs)
        assert response.status_code == 401, path
        assert response.json() == {"detail": "invalid or missing API key"}
