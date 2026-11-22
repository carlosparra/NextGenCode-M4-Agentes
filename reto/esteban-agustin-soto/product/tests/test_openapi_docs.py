"""Pruebas de la documentación OpenAPI pública (sesión 6).

La documentación no pide clave, pero documentarla no debe cambiar el
comportamiento de ``/ask`` y ``/metrics``. Todo sin red y con datos ficticios.
"""

import json

import pytest

from conftest import ANA_KEY, BOB_KEY

from app.pii import mask_text

ROUTES = {"/": "get", "/health": "get", "/ask": "post", "/metrics": "get"}
AUTO_SUMMARIES = {"Index", "Health", "Ask", "Get Metrics"}
UNAUTHORIZED = {"detail": "invalid or missing API key"}


@pytest.fixture(name="schema")
def schema_fixture(make_secure_client):
    """Esquema ``/openapi.json`` pedido sin clave.

    :param make_secure_client: Fábrica de clientes sin clave por omisión.
    :type make_secure_client: collections.abc.Callable
    :return: El esquema OpenAPI como diccionario.
    :rtype: dict
    """
    client, _, _ = make_secure_client()
    response = client.get("/openapi.json")
    assert response.status_code == 200
    return response.json()


def _operation(schema, path):
    """Devuelve la operación de una ruta del producto.

    :param schema: Esquema OpenAPI.
    :type schema: dict
    :param path: Ruta, por ejemplo ``/ask``.
    :type path: str
    :return: La operación del método que usa esa ruta.
    :rtype: dict
    """
    return schema["paths"][path][ROUTES[path]]


def _resolve(schema, node):
    """Sigue una referencia ``$ref`` del esquema hasta su definición.

    :param schema: Esquema OpenAPI.
    :type schema: dict
    :param node: Nodo que puede ser una referencia.
    :type node: dict
    :return: El nodo ya resuelto.
    :rtype: dict
    """
    while "$ref" in node:
        target = schema
        for part in node["$ref"].lstrip("#/").split("/"):
            target = target[part]
        node = target
    return node


def test_docs_openapi_and_redoc_are_public(make_secure_client):
    client, _, _ = make_secure_client()
    for path in ("/docs", "/openapi.json", "/redoc"):
        assert client.get(path).status_code == 200, path


def test_schema_describes_the_four_routes_in_detail(schema):
    for path in ROUTES:
        operation = _operation(schema, path)
        assert operation["summary"] not in AUTO_SUMMARIES, path
        assert operation["description"].strip(), path
        assert operation["tags"], path


def test_ask_documents_its_error_responses(schema):
    responses = _operation(schema, "/ask")["responses"]
    assert {"200", "401", "422", "429", "502"} <= set(responses)


def test_metrics_documents_unauthorized_and_rate_limit(schema):
    responses = _operation(schema, "/metrics")["responses"]
    assert {"200", "401", "429"} <= set(responses)


def test_rate_limit_response_declares_retry_after(schema):
    for path in ("/ask", "/metrics"):
        headers = _operation(schema, path)["responses"]["429"]["headers"]
        assert "Retry-After" in headers, path


def test_x_api_key_is_declared_as_a_header_security_scheme(schema):
    schemes = schema["components"]["securitySchemes"].values()
    assert any(
        scheme["type"] == "apiKey" and scheme["in"] == "header"
        and scheme["name"] == "X-API-Key"
        for scheme in schemes
    )


def test_only_ask_and_metrics_require_the_key(schema):
    for path in ("/ask", "/metrics"):
        assert _operation(schema, path).get("security"), path
    for path in ("/", "/health"):
        assert not _operation(schema, path).get("security"), path


def test_ask_response_schema_matches_a_real_response(schema, make_costs_client):
    client, _ = make_costs_client()
    real = client.post("/ask", json={"question": "Who is EMP-0004?"}).json()
    content = _operation(schema, "/ask")["responses"]["200"]["content"]
    documented = _resolve(schema, content["application/json"]["schema"])
    assert set(documented["properties"]) == set(real)


@pytest.mark.parametrize("path, method", [("/ask", "post"), ("/metrics", "get")])
def test_missing_key_is_a_401_with_the_same_body_and_not_a_403(
    make_secure_client, path, method
):
    client, _, _ = make_secure_client()
    response = client.request(method, path, json={"question": "Hi"}
                              if method == "post" else None)
    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED


def test_invalid_body_without_a_key_is_still_a_401(make_secure_client):
    client, _, _ = make_secure_client()
    response = client.post("/ask", json={"wrong": "body"})
    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED


def test_schema_contains_no_client_key_curp_or_email(schema):
    text = json.dumps(schema, ensure_ascii=False)
    assert ANA_KEY not in text
    assert BOB_KEY not in text
    assert mask_text(text) == text


def test_schema_examples_use_employee_emp_0004(schema):
    assert "EMP-0004" in json.dumps(schema, ensure_ascii=False)
