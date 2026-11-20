"""Cliente del modelo real a traves de Cloudflare AI Gateway.

``GatewayModel`` hace un POST al endpoint compatible con OpenAI de
Workers AI detras de AI Gateway, con ``max_tokens`` (palanca 3) y, si
el TTL es mayor que 0, el encabezado ``cf-aig-cache-ttl`` (palanca 4).
Lee los tokens de ``usage`` y marca la llamada como cacheada si el
gateway responde ``cf-aig-cache-status: HIT``.

El ``httpx.Client`` se inyecta: en las pruebas usa
``httpx.MockTransport`` y nunca toca la red. Cualquier falla se
convierte en ``ModelUnavailable`` con un mensaje sin el token.

:seealso: ``spec/03-costs.md`` punto 1 y ADR 0007.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.completion import Completion, Model, ModelUnavailable
from app.config import Settings
from app.prompts import DIRECTORY_PROMPT

GATEWAY_URL = (
    "https://gateway.ai.cloudflare.com/v1/{account_id}/{gateway_id}"
    "/workers-ai/v1/chat/completions"
)
GATEWAY_TIMEOUT_SECONDS = 30.0
CACHE_TTL_HEADER = "cf-aig-cache-ttl"
CACHE_STATUS_HEADER = "cf-aig-cache-status"
CACHE_HIT = "HIT"
FIRST_ERROR_STATUS = 400
# Spec 06: el prompt de siempre vive en ``app.prompts``; se conserva el
# nombre para quien lo importe desde aqui.
SYSTEM_PROMPT = DIRECTORY_PROMPT
SYSTEM_ROLE = "system"


class GatewayModel(Model):
    """Modelo de Workers AI llamado a traves de AI Gateway.

    :param name: Nombre del modelo en Workers AI (por ejemplo
        ``@cf/meta/llama-3.1-8b-instruct-fast``).
    :type name: str
    :param settings: Configuracion con cuenta, gateway, token, tope de
        salida, temperatura y TTL de cache.
    :type settings: app.config.Settings
    :param client: Cliente HTTP; si falta, se crea uno con tiempo
        maximo de ``GATEWAY_TIMEOUT_SECONDS``.
    :type client: httpx.Client | None
    """

    def __init__(
        self,
        name: str,
        settings: Settings,
        client: httpx.Client | None = None,
    ) -> None:
        """Guarda el nombre, la configuracion y el cliente HTTP.

        :param name: Nombre del modelo.
        :type name: str
        :param settings: Configuracion validada.
        :type settings: app.config.Settings
        :param client: Cliente HTTP inyectable.
        :type client: httpx.Client | None
        """
        self.name = name
        self._settings = settings
        self._client = client or httpx.Client(timeout=GATEWAY_TIMEOUT_SECONDS)
        self._url = GATEWAY_URL.format(
            account_id=settings.cf_account_id, gateway_id=settings.cf_gateway_id
        )

    def complete(self, messages: list[dict[str, str]]) -> Completion:
        """Llama al gateway y devuelve el texto y los tokens.

        :param messages: Mensajes de la conversacion; si no traen un
            prompt de sistema, se agrega aqui el de ``directory``.
        :type messages: list[dict[str, str]]
        :return: Texto del modelo, tokens y si vino de la cache.
        :rtype: app.completion.Completion
        :raises app.completion.ModelUnavailable: Si la llamada falla,
            el status es de error o el cuerpo no es valido.
        """
        response = self._post(messages)
        if response.status_code >= FIRST_ERROR_STATUS:
            raise ModelUnavailable(f"gateway status {response.status_code}")
        text, input_tokens, output_tokens = self._parse(response)
        cached = response.headers.get(CACHE_STATUS_HEADER, "").upper() == CACHE_HIT
        return Completion(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached=cached,
        )

    def _headers(self) -> dict[str, str]:
        """Arma los encabezados de la llamada.

        :return: ``Authorization`` y, si aplica, ``cf-aig-cache-ttl``.
        :rtype: dict[str, str]
        """
        token = self._settings.cf_api_token.get_secret_value()
        headers = {"Authorization": f"Bearer {token}"}
        if self._settings.cache_ttl_seconds > 0:
            headers[CACHE_TTL_HEADER] = str(self._settings.cache_ttl_seconds)
        return headers

    def _body(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        """Arma el cuerpo ``{model, messages, max_tokens, temperature}``.

        Spec 06: si los mensajes ya traen un ``system`` (supervisor o
        especialista ``policy``), se respeta; si no, se antepone el
        prompt del especialista ``directory``, como siempre.

        :param messages: Mensajes de la conversacion.
        :type messages: list[dict[str, str]]
        :return: Cuerpo JSON de la llamada.
        :rtype: dict[str, Any]
        """
        if messages and messages[0].get("role") == SYSTEM_ROLE:
            full = list(messages)
        else:
            full = [{"role": SYSTEM_ROLE, "content": SYSTEM_PROMPT}, *messages]
        return {
            "model": self.name,
            "messages": full,
            "max_tokens": self._settings.model_max_tokens,
            "temperature": self._settings.model_temperature,
        }

    def _post(self, messages: list[dict[str, str]]) -> httpx.Response:
        """Hace el POST al gateway.

        :param messages: Mensajes de la conversacion.
        :type messages: list[dict[str, str]]
        :return: Respuesta HTTP sin interpretar.
        :rtype: httpx.Response
        :raises app.completion.ModelUnavailable: Si la red falla o se
            agota el tiempo. Solo se guarda el tipo de error.
        """
        try:
            return self._client.post(
                self._url,
                json=self._body(messages),
                headers=self._headers(),
                timeout=GATEWAY_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            raise ModelUnavailable(f"gateway {type(exc).__name__}") from None

    @staticmethod
    def _parse(response: httpx.Response) -> tuple[str, int, int]:
        """Lee el texto y los tokens del cuerpo de la respuesta.

        :param response: Respuesta exitosa del gateway.
        :type response: httpx.Response
        :return: Texto, tokens de entrada y tokens de salida.
        :rtype: tuple[str, int, int]
        :raises app.completion.ModelUnavailable: Si el JSON esta roto o
            faltan ``choices`` o ``usage``.
        """
        try:
            data = response.json()
            text = data["choices"][0]["message"]["content"]
            usage = data["usage"]
            input_tokens = int(usage["prompt_tokens"])
            output_tokens = int(usage["completion_tokens"])
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ModelUnavailable(f"gateway body {type(exc).__name__}") from None
        if not isinstance(text, str):
            raise ModelUnavailable("gateway body without text")
        return text, input_tokens, output_tokens
