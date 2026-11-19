"""Modelo real: Cloudflare Workers AI a traves de AI Gateway.

``GatewayLLM`` cumple el protocolo ``LLM``. El cliente ``httpx`` se inyecta para
que las pruebas usen un transporte falso y nunca llamen a la red. Cualquier
fallo se convierte en ``ModelUnavailable`` con un mensaje que no lleva ni la
peticion ni el token.
"""

import httpx

from app.completion import Completion
from app.config import Settings

GATEWAY_URL_TEMPLATE = (
    "https://gateway.ai.cloudflare.com/v1/{account_id}/{gateway_id}"
    "/workers-ai/v1/chat/completions"
)
CACHE_TTL_HEADER = "cf-aig-cache-ttl"
CACHE_STATUS_HEADER = "cf-aig-cache-status"
CACHE_HIT = "HIT"
# Sin reintentos automaticos: cada reintento cuesta.
GATEWAY_TIMEOUT_SECONDS = 30.0


class ModelUnavailable(RuntimeError):
    """El modelo real no respondio o respondio algo que no se puede usar."""


def build_http_client() -> httpx.Client:
    """Crea el cliente HTTP de produccion con un tiempo limite fijo.

    :return: Cliente ``httpx`` sin reintentos
    :rtype: httpx.Client
    """
    return httpx.Client(timeout=GATEWAY_TIMEOUT_SECONDS)


class GatewayLLM:  # pylint: disable=too-few-public-methods
    """Modelo de Workers AI llamado por AI Gateway.

    :param settings: Configuracion con la cuenta, el token y las palancas
    :type settings: app.config.Settings
    :param model: Nombre del modelo de Workers AI
    :type model: str
    :param client: Cliente HTTP (en pruebas, con ``httpx.MockTransport``)
    :type client: httpx.Client
    """

    def __init__(self, settings: Settings, model: str, client: httpx.Client):
        self._settings = settings
        self._model = model
        self._client = client
        self._url = GATEWAY_URL_TEMPLATE.format(
            account_id=settings.cf_account_id, gateway_id=settings.cf_gateway_id
        )

    def complete(self, messages: list) -> Completion:
        """Pide al gateway la siguiente respuesta.

        :param messages: Mensajes con ``role`` y ``content``
        :type messages: list[dict]
        :return: Texto, tokens, nombre del modelo y si vino de la cache
        :rtype: app.completion.Completion
        :raises ModelUnavailable: Si la llamada falla o la respuesta no sirve
        """
        body = {
            "model": self._model,
            "messages": messages,
            "max_tokens": self._settings.model_max_tokens,
            "temperature": self._settings.model_temperature,
        }
        try:
            response = self._client.post(self._url, headers=self._headers(), json=body)
        except httpx.HTTPError as error:
            # Solo el tipo: el error original lleva la peticion con el token.
            raise ModelUnavailable(
                f"Gateway request failed: {type(error).__name__}"
            ) from None
        if not response.is_success:
            raise ModelUnavailable(
                f"Gateway answered with status {response.status_code}"
            )
        return self._parse(response)

    def _headers(self) -> dict:
        """Arma los encabezados: token y, si aplica, el TTL de la cache.

        :return: Encabezados de la peticion
        :rtype: dict[str, str]
        """
        headers = {"Authorization": f"Bearer {self._settings.cf_api_token}"}
        if self._settings.cache_ttl_seconds > 0:
            headers[CACHE_TTL_HEADER] = str(self._settings.cache_ttl_seconds)
        return headers

    def _parse(self, response: httpx.Response) -> Completion:
        """Lee texto, tokens y estado de cache de la respuesta del gateway.

        :param response: Respuesta exitosa del gateway
        :type response: httpx.Response
        :return: La respuesta del modelo
        :rtype: app.completion.Completion
        :raises ModelUnavailable: Si faltan ``choices`` o ``usage``
        """
        try:
            data = response.json()
            text = data["choices"][0]["message"]["content"]
            input_tokens = int(data["usage"]["prompt_tokens"])
            output_tokens = int(data["usage"]["completion_tokens"])
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise ModelUnavailable(
                f"Gateway answer is incomplete: {type(error).__name__}"
            ) from None
        if not isinstance(text, str):
            raise ModelUnavailable("Gateway answer text is not a string")
        status = response.headers.get(CACHE_STATUS_HEADER, "")
        return Completion(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=self._model,
            cached=status.strip().upper() == CACHE_HIT,
        )
