"""Modelo real: Workers AI a través de Cloudflare AI Gateway, con ``httpx``."""

import httpx

from app.model_reply import ModelReply

GATEWAY_URL = (
    "https://gateway.ai.cloudflare.com/v1/{account_id}/{gateway_id}"
    "/workers-ai/v1/chat/completions"
)
GATEWAY_TIMEOUT_SECONDS = 15.0
CACHE_TTL_HEADER = "cf-aig-cache-ttl"
CACHE_STATUS_HEADER = "cf-aig-cache-status"
CACHE_HIT = "HIT"


class ModelUnavailableError(RuntimeError):
    """El modelo no respondió o respondió algo que no se puede usar.

    El mensaje nunca incluye el token, la URL ni el cuerpo de la respuesta.
    """


def default_http_client() -> httpx.Client:
    """Crea el cliente HTTP real, con un tiempo de espera fijo.

    :return: Cliente HTTP
    :rtype: httpx.Client
    """
    return httpx.Client(timeout=GATEWAY_TIMEOUT_SECONDS)


def _read_reply(response: httpx.Response) -> ModelReply:
    """Extrae texto, tokens y estado de caché de la respuesta del gateway.

    :param response: Respuesta HTTP con formato de chat completions
    :type response: httpx.Response
    :return: Respuesta del modelo
    :rtype: ModelReply
    :raises ModelUnavailableError: Si el estado no es 2xx o el cuerpo no sirve
    """
    if not response.is_success:
        raise ModelUnavailableError(f"gateway answered {response.status_code}")
    try:
        body = response.json()
        text = body["choices"][0]["message"]["content"]
        usage = body.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens", 0))
        output_tokens = int(usage.get("completion_tokens", 0))
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
        raise ModelUnavailableError("gateway answered an invalid body") from error
    if not isinstance(text, str):
        raise ModelUnavailableError("gateway answered without text")
    cache_status = response.headers.get(CACHE_STATUS_HEADER, "")
    return ModelReply(
        text=text,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached=cache_status.strip().upper() == CACHE_HIT,
    )


class GatewayModel:
    """Modelo de Workers AI llamado a través de AI Gateway.

    :param name: Nombre del modelo en Workers AI
    :type name: str
    :param gateway_settings: Cuenta, gateway, token y parámetros de la llamada
    :type gateway_settings: app.config.GatewaySettings
    :param http_client: Cliente HTTP inyectado (en pruebas, con transporte simulado)
    :type http_client: httpx.Client
    """

    def __init__(self, name: str, gateway_settings, http_client: httpx.Client):
        self.name = name
        self._settings = gateway_settings
        self._client = http_client
        self._url = GATEWAY_URL.format(
            account_id=gateway_settings.account_id,
            gateway_id=gateway_settings.gateway_id,
        )

    def _headers(self) -> dict:
        """Arma los encabezados: token y, si aplica, la vida de la caché.

        :return: Encabezados de la llamada
        :rtype: dict
        """
        headers = {"Authorization": f"Bearer {self._settings.api_token.reveal()}"}
        if self._settings.cache_ttl_seconds > 0:
            headers[CACHE_TTL_HEADER] = str(self._settings.cache_ttl_seconds)
        return headers

    def complete(self, messages: list[dict]) -> ModelReply:
        """Pide la siguiente respuesta de la conversación al gateway.

        :param messages: Mensajes con ``role`` y ``content``
        :type messages: list[dict]
        :return: Respuesta con tokens de ``usage`` y si fue de caché
        :rtype: ModelReply
        :raises ModelUnavailableError: Si la llamada falla por cualquier motivo
        """
        body = {
            "model": self.name,
            "messages": messages,
            "max_tokens": self._settings.max_tokens,
            "temperature": self._settings.temperature,
        }
        try:
            response = self._client.post(self._url, json=body, headers=self._headers())
        except httpx.HTTPError as error:
            # Solo el tipo: el mensaje de httpx puede incluir la URL con la cuenta.
            raise ModelUnavailableError(
                f"gateway call failed: {type(error).__name__}"
            ) from error
        return _read_reply(response)
