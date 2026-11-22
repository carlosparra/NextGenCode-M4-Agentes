"""Tests de la causa de una falla del modelo, sin red y sin filtrar secretos."""

import httpx
import pytest

from conftest import GATEWAY_ENV, log_lines

from app.config import load_settings
from app.llm import GatewayModel, ModelUnavailable

MESSAGES = [{"role": "user", "content": "hello"}]
SECRET_TOKEN = "cf-secret-token-98765"
SECRET_ACCOUNT = "private-account-4321"
SECRET_BODY = "SECRET-BODY-FROM-CLOUDFLARE"
SECRET_ENV = {"CF_API_TOKEN": SECRET_TOKEN, "CF_ACCOUNT_ID": SECRET_ACCOUNT}


def _failure(handler):
    """Llama al modelo y devuelve la excepción ``ModelUnavailable``.

    :param handler: Manejador de ``httpx.MockTransport``
    :type handler: collections.abc.Callable
    :return: La excepción capturada
    :rtype: app.llm.ModelUnavailable
    """
    settings = load_settings({**GATEWAY_ENV, **SECRET_ENV})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    model = GatewayModel("small-model", settings, client=client)
    with pytest.raises(ModelUnavailable) as caught:
        model.generate(MESSAGES)
    return caught.value


def _timeout(request):
    raise httpx.ConnectTimeout("slow", request=request)


def _status(code):
    return lambda request: httpx.Response(code, text=SECRET_BODY)


def test_not_found_response_keeps_cause_and_status_code():
    error = _failure(_status(404))
    assert error.cause == "HTTPStatusError"
    assert error.status_code == 404


def test_unauthorized_response_keeps_cause_and_status_code():
    error = _failure(_status(401))
    assert error.cause == "HTTPStatusError"
    assert error.status_code == 401


def test_timeout_keeps_cause_and_has_no_status_code():
    error = _failure(_timeout)
    assert error.cause == "ConnectTimeout"
    assert error.status_code is None


def test_body_without_choices_and_usage_is_a_key_error():
    error = _failure(lambda request: httpx.Response(200, json={"id": "x"}))
    assert error.cause == "KeyError"
    assert error.status_code is None


def test_invalid_json_body_keeps_its_cause_without_status_code():
    error = _failure(lambda request: httpx.Response(200, text="not json"))
    assert error.cause == "JSONDecodeError"
    assert error.status_code is None


@pytest.mark.parametrize("handler", [_status(404), _status(401), _timeout])
def test_error_message_has_no_url_or_secret(handler):
    message = str(_failure(handler))
    for forbidden in ("http", "cloudflare", SECRET_TOKEN, SECRET_ACCOUNT,
                      SECRET_BODY, "Bearer"):
        assert forbidden not in message


def _failed_ask(make_costs_client, handler):
    """Hace un ``POST /ask`` que falla y devuelve respuesta, flujo y línea.

    :param make_costs_client: Fábrica de clientes con modelos del gateway
    :type make_costs_client: collections.abc.Callable
    :param handler: Manejador de ``httpx.MockTransport``
    :type handler: collections.abc.Callable
    :return: Respuesta, texto completo de la bitácora y línea del 502
    :rtype: tuple
    """
    client, stream = make_costs_client(env=SECRET_ENV, handler=handler)
    response = client.post(
        "/ask", json={"question": "Who is EMP-0001?"},
        headers={"X-Request-ID": "req-502"},
    )
    lines = [line for line in log_lines(stream)
             if line.get("error_type") == "ModelUnavailable"]
    return response, stream.getvalue(), lines


def test_bad_gateway_log_line_has_cause_and_status_code(make_costs_client):
    response, _, lines = _failed_ask(make_costs_client, _status(404))
    assert response.status_code == 502
    assert len(lines) == 1
    line = lines[0]
    assert line["event"] == "error"
    assert line["cause"] == "HTTPStatusError"
    assert line["status_code"] == 404
    assert line["client"] == "ana"
    assert line["request_id"] == "req-502"


def test_bad_gateway_log_line_for_timeout_has_null_status_code(
        make_costs_client):
    _, _, lines = _failed_ask(make_costs_client, _timeout)
    assert lines[0]["cause"] == "ConnectTimeout"
    assert lines[0]["status_code"] is None


def test_bad_gateway_logs_never_include_body_headers_or_secrets(
        make_costs_client):
    _, text, lines = _failed_ask(make_costs_client, _status(401))
    assert lines
    for forbidden in (SECRET_BODY, SECRET_TOKEN, SECRET_ACCOUNT, "Bearer",
                      "Authorization", "http"):
        assert forbidden not in text
