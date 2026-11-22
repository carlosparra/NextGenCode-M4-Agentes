"""Interfaz del modelo y modelo simulado determinista."""

import json
import re
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.directory import normalize

GATEWAY_URL = (
    "https://gateway.ai.cloudflare.com/v1/{account}/{gateway}"
    "/workers-ai/v1/chat/completions"
)
REQUEST_TIMEOUT_SECONDS = 30
TOOL_RESULT_PREFIX = "Resultado de la herramienta: "
TOOL_RESULT_INSTRUCTION = (
    '\n\nAhora responde con {"answer": ...} usando este resultado.'
)
HELP_MESSAGE = "Pregúntame por un empleado (EMP-0001) o un departamento."
_EMPLOYEE_ID = re.compile(r"EMP-\d{4}")


class Model(Protocol):
    """Interfaz que el agente usa para hablar con cualquier modelo."""

    def complete(self, messages):
        """Responde con un único objeto JSON en texto.

        :param messages: Mensajes con ``role`` y ``content``
        :type messages: list
        :return: JSON con ``tool``/``args`` o con ``answer``
        :rtype: str
        """


def count_tokens(text):
    """Cuenta tokens de forma aproximada (palabras).

    :param text: Texto a medir
    :type text: str
    :return: Número de palabras
    :rtype: int
    """
    return len(text.split())


def approximate_completion(messages, text):
    """Arma una ``Completion`` con tokens aproximados (palabras), sin caché.

    :param messages: Mensajes enviados al modelo
    :type messages: list
    :param text: Texto que devolvió el modelo
    :type text: str
    :return: La respuesta con su uso aproximado
    :rtype: Completion
    """
    return Completion(
        text=text,
        input_tokens=sum(count_tokens(m["content"]) for m in messages),
        output_tokens=count_tokens(text),
        cached=False,
    )


class ModelUnavailable(Exception):
    """El modelo real no respondió bien (red, estado o cuerpo inválido).

    El mensaje es solo el nombre de la causa: nunca incluye URL, cuerpo,
    cabeceras ni credenciales.

    :param cause: Nombre de la excepción original
    :type cause: str
    :param status_code: Código HTTP si la causa fue un estado de error
    :type status_code: int or None
    """

    def __init__(self, cause, status_code=None):
        super().__init__(cause)
        self.cause = cause
        self.status_code = status_code


@dataclass(frozen=True)
class Completion:
    """Respuesta de un modelo con su uso.

    :param text: Texto devuelto por el modelo
    :type text: str
    :param input_tokens: Tokens de entrada
    :type input_tokens: int
    :param output_tokens: Tokens de salida
    :type output_tokens: int
    :param cached: Si vino de la caché del gateway
    :type cached: bool
    """

    text: str
    input_tokens: int
    output_tokens: int
    cached: bool = False


class GatewayModel:
    """Modelo real de Workers AI a través de AI Gateway.

    :param name: Nombre del modelo en Workers AI
    :type name: str
    :param settings: Configuración con ``cf_*``, tope de tokens y caché
    :type settings: app.config.Settings
    :param client: Cliente ``httpx.Client`` inyectable; por omisión uno nuevo
    :type client: httpx.Client or None
    """

    def __init__(self, name, settings, client=None):
        self.name = name
        self._settings = settings
        self._client = client or httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS)

    def _url(self):
        """Arma la URL del gateway.

        :return: URL de ``chat/completions``
        :rtype: str
        """
        return GATEWAY_URL.format(
            account=self._settings.cf_account_id,
            gateway=self._settings.cf_gateway_id,
        )

    def _headers(self):
        """Arma los encabezados, con la caché solo si el TTL es mayor que 0.

        :return: Encabezados de la petición
        :rtype: dict
        """
        headers = {"Authorization": f"Bearer {self._settings.cf_api_token}"}
        if self._settings.cache_ttl_seconds > 0:
            headers["cf-aig-cache-ttl"] = str(self._settings.cache_ttl_seconds)
        return headers

    def generate(self, messages):
        """Llama al gateway y lee texto, tokens y estado de la caché.

        :param messages: Mensajes con ``role`` y ``content``
        :type messages: list
        :return: La respuesta con su uso
        :rtype: Completion
        :raises ModelUnavailable: Ante cualquier falla de la llamada
        """
        body = {
            "model": self.name,
            "messages": messages,
            "max_tokens": self._settings.model_max_tokens,
            "temperature": self._settings.model_temperature,
        }
        try:
            response = self._client.post(
                self._url(), headers=self._headers(), json=body
            )
            response.raise_for_status()
            data = response.json()
            usage = data["usage"]
            content = data["choices"][0]["message"]["content"]
            if isinstance(content, (dict, list)):
                content = json.dumps(content, ensure_ascii=False)
            return Completion(
                text=content,
                input_tokens=int(usage["prompt_tokens"]),
                output_tokens=int(usage["completion_tokens"]),
                cached=response.headers.get("cf-aig-cache-status", "").upper()
                == "HIT",
            )
        except (httpx.HTTPError, ValueError, KeyError, IndexError,
                TypeError) as error:
            status_code = (
                error.response.status_code
                if isinstance(error, httpx.HTTPStatusError) else None
            )
            raise ModelUnavailable(
                type(error).__name__, status_code
            ) from error

    def complete(self, messages):
        """Devuelve solo el texto de ``generate``.

        :param messages: Mensajes con ``role`` y ``content``
        :type messages: list
        :return: JSON con ``tool``/``args`` o con ``answer``
        :rtype: str
        """
        return self.generate(messages).text


class FakeModel:
    """Modelo simulado: decide con reglas sobre el último mensaje.

    :param departments: Departamentos que existen en los datos
    :type departments: list
    :param name: Nombre del modelo, para costearlo con su precio
    :type name: str
    """

    def __init__(self, departments, name="fake"):
        self._departments = list(departments)
        self.name = name

    def generate(self, messages):
        """Responde como ``complete`` y cuenta tokens de forma aproximada.

        :param messages: Mensajes con ``role`` y ``content``
        :type messages: list
        :return: La respuesta con tokens aproximados
        :rtype: Completion
        """
        return approximate_completion(messages, self.complete(messages))

    def complete(self, messages):
        """Aplica las reglas en orden y devuelve un JSON.

        :param messages: Mensajes con ``role`` y ``content``
        :type messages: list
        :return: JSON con ``tool``/``args`` o con ``answer``
        :rtype: str
        """
        last = messages[-1]["content"] if messages else ""
        if last.startswith(TOOL_RESULT_PREFIX):
            result = last[len(TOOL_RESULT_PREFIX):]
            result = result.removesuffix(TOOL_RESULT_INSTRUCTION)
            reply = {"answer": f"Según el directorio: {result}"}
        else:
            reply = self._decide(last)
        return json.dumps(reply, ensure_ascii=False)

    def _decide(self, text):
        """Elige entre pedir una herramienta o dar la ayuda.

        :param text: Último mensaje del usuario
        :type text: str
        :return: Objeto de respuesta del protocolo
        :rtype: dict
        """
        match = _EMPLOYEE_ID.search(text.upper())
        if match:
            return {"tool": "get_employee",
                    "args": {"employee_id": match.group(0)}}
        normalized = normalize(text)
        for department in self._departments:
            if normalize(department) in normalized:
                return {"tool": "search_by_department",
                        "args": {"department": department}}
        return {"answer": HELP_MESSAGE}


def build_model(provider, departments):
    """Elige el modelo según el proveedor.

    :param provider: Valor de ``MODEL_PROVIDER``
    :type provider: str
    :param departments: Departamentos existentes
    :type departments: list
    :return: El modelo configurado
    :rtype: Model
    :raises ValueError: Si el proveedor no existe
    """
    if provider == "fake":
        return FakeModel(departments)
    raise ValueError(f"Unknown model provider: {provider!r}")


def build_models(settings, departments):
    """Crea un modelo por nombre (el pequeño y el grande).

    :param settings: Configuración con proveedor y nombres de modelos
    :type settings: app.config.Settings
    :param departments: Departamentos existentes
    :type departments: list
    :return: Diccionario ``nombre -> modelo``
    :rtype: dict
    :raises ValueError: Si el proveedor no existe
    """
    names = {settings.model_small, settings.model_large}
    if settings.model_provider == "fake":
        return {name: FakeModel(departments, name) for name in names}
    if settings.model_provider == "gateway":
        return {name: GatewayModel(name, settings) for name in names}
    raise ValueError(f"Unknown model provider: {settings.model_provider!r}")
