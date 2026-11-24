"""Modelo real: Cloudflare Workers AI a través de AI Gateway.

- Gateway autenticado: manda ``cf-aig-authorization`` además del token.
- Caché del gateway con ``cf-aig-cache-ttl``; un ``HIT`` no cuesta.
- Tiempo límite y reintentos con espera exponencial ante 429/5xx o red.
"""

from __future__ import annotations

import asyncio

import httpx

from app.config import Settings
from app.llm.base import Completion, ModelUnavailable

GATEWAY_URL = (
    "https://gateway.ai.cloudflare.com/v1/{account}/{gateway}"
    "/workers-ai/v1/chat/completions"
)
_RETRYABLE = {408, 429, 500, 502, 503, 504}


class GatewayModel:
    """Cliente asíncrono del AI Gateway de Cloudflare.

    :param settings: Configuración (cuenta, gateway, token, tiempos)
    :type settings: Settings
    :param transport: Transporte HTTP (las pruebas inyectan uno simulado)
    :type transport: httpx.AsyncBaseTransport | None
    :param sleep: Función de espera (las pruebas la anulan)
    :type sleep: Callable
    """

    def __init__(self, settings: Settings, transport=None, sleep=asyncio.sleep) -> None:
        self._url = GATEWAY_URL.format(
            account=settings.cf_account_id, gateway=settings.cf_gateway_id
        )
        headers = {"Authorization": f"Bearer {settings.cf_api_token}"}
        if settings.cf_gateway_auth:
            headers["cf-aig-authorization"] = f"Bearer {settings.cf_api_token}"
        if settings.cache_ttl_seconds > 0:
            headers["cf-aig-cache-ttl"] = str(settings.cache_ttl_seconds)
        else:
            # Sin caché de verdad, aunque el gateway la tenga encendida
            headers["cf-aig-skip-cache"] = "true"
        self._client = httpx.AsyncClient(
            headers=headers,
            timeout=settings.model_timeout_seconds,
            transport=transport,
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
        )
        self._temperature = settings.model_temperature
        self._retries = settings.model_retries
        self._sleep = sleep

    async def complete(
        self, messages: list[dict], model: str, max_tokens: int
    ) -> Completion:
        """Llama al modelo con reintentos.

        :param messages: Conversación
        :type messages: list[dict]
        :param model: Modelo de Workers AI
        :type model: str
        :param max_tokens: Tope de tokens de salida
        :type max_tokens: int
        :return: Respuesta del modelo
        :rtype: Completion
        :raises ModelUnavailable: Si falla después de los reintentos
        """
        body = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": self._temperature,
        }
        last_error = "unknown"
        for attempt in range(self._retries + 1):
            try:
                response = await self._client.post(self._url, json=body)
            except httpx.HTTPError as exc:
                last_error = type(exc).__name__
            else:
                if response.status_code == 200:
                    return self._parse(response, model)
                last_error = f"http_{response.status_code}"
                if response.status_code not in _RETRYABLE:
                    break
            if attempt < self._retries:
                await self._sleep(0.5 * 2**attempt)
        raise ModelUnavailable(last_error)

    @staticmethod
    def _parse(response: httpx.Response, model: str) -> Completion:
        try:
            data = response.json()
            text = data["choices"][0]["message"]["content"] or ""
            usage = data.get("usage") or {}
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ModelUnavailable("bad_response") from exc
        cached = response.headers.get("cf-aig-cache-status", "").upper() == "HIT"
        return Completion(
            text=text,
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
            model=model,
            cached=cached,
        )

    async def aclose(self) -> None:
        """Cierra las conexiones HTTP."""
        await self._client.aclose()
