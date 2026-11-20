"""Interfaz del modelo (``complete(messages)``) y sus proveedores (ADR 0002 y 0006).

- :class:`FakeModel`: simulado determinista, con nombre para calcular su precio.
- :class:`GatewayModel`: modelo real de Workers AI a través de Cloudflare AI
  Gateway, con un cliente ``httpx`` inyectado para que las pruebas no usen la red.
"""

import json
import re
from dataclasses import dataclass
from typing import Protocol

import httpx

TOOL_RESULT_PREFIX = "Resultado de la herramienta: "
HELP_ANSWER = "Pregúntame por un empleado (EMP-0001) o un departamento."
EMPLOYEE_ID_PATTERN = re.compile(r"EMP-\d{4}")
GATEWAY_URL_TEMPLATE = (
    "https://gateway.ai.cloudflare.com/v1/{account}/{gateway}"
    "/workers-ai/v1/chat/completions"
)
GATEWAY_TIMEOUT_SECONDS = 30.0
CACHE_TTL_HEADER = "cf-aig-cache-ttl"
CACHE_STATUS_HEADER = "cf-aig-cache-status"
CACHE_HIT = "HIT"
CODE_FENCE_PATTERN = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")
SYSTEM_PROMPT = (
    "Eres el asistente de Recursos Humanos. Responde siempre en español y solo "
    "con un objeto JSON, sin texto adicional. Para responder usa "
    '{"answer": "<respuesta>"}. Para consultar el directorio usa '
    '{"tool": "get_employee", "args": {"employee_id": "EMP-0001"}} o '
    '{"tool": "search_by_department", "args": {"department": "<nombre>"}}. '
    "El resultado de la herramienta llega en un mensaje que empieza con "
    f"'{TOOL_RESULT_PREFIX.strip()}'. No inventes datos."
)


class ModelUnavailableError(RuntimeError):
    """El modelo real no respondió o respondió algo inutilizable."""


@dataclass(frozen=True)
class ModelReply:
    """Respuesta de un modelo.

    :param text: Texto JSON devuelto por el modelo
    :type text: str
    :param input_tokens: Tokens de entrada consumidos
    :type input_tokens: int
    :param output_tokens: Tokens de salida generados
    :type output_tokens: int
    :param model: Nombre del modelo que respondió (para su precio)
    :type model: str
    :param cached: Si la respuesta salió de la caché del gateway
    :type cached: bool
    """

    text: str
    input_tokens: int
    output_tokens: int
    model: str = "fake"
    cached: bool = False


class LanguageModel(Protocol):
    """Protocolo que cumple todo modelo usado por el agente."""

    def complete(self, messages):
        """Devuelve la siguiente respuesta del modelo.

        :param messages: Conversación con ``role`` y ``content``
        :type messages: list[dict]
        :return: La respuesta del modelo
        :rtype: ModelReply
        """


def _count_words(text):
    """Cuenta palabras separadas por espacios.

    :param text: Texto a contar
    :type text: str
    :return: Número de palabras
    :rtype: int
    """
    return len(str(text).split())


class FakeModel:
    """Modelo simulado determinista, sin red.

    Responde igual sin importar su nombre; el nombre solo decide su precio.

    :param name: Nombre del modelo (``MODEL_SMALL`` o ``MODEL_LARGE``)
    :type name: str
    :param departments: Departamentos que existen en los datos
    :type departments: list[str]
    """

    def __init__(self, name, departments):
        self.name = name
        self._departments = list(departments)

    def _decide(self, content):
        """Aplica las reglas del modelo simulado al último mensaje.

        :param content: Contenido del último mensaje
        :type content: str
        :return: Objeto de decisión (herramienta o respuesta)
        :rtype: dict
        """
        if content.startswith(TOOL_RESULT_PREFIX):
            result = content[len(TOOL_RESULT_PREFIX):]
            return {"answer": f"Según el directorio: {result}"}
        match = EMPLOYEE_ID_PATTERN.search(content)
        if match:
            return {"tool": "get_employee", "args": {"employee_id": match.group(0)}}
        lowered = content.lower()
        for department in self._departments:
            if department.lower() in lowered:
                return {
                    "tool": "search_by_department",
                    "args": {"department": department},
                }
        return {"answer": HELP_ANSWER}

    def complete(self, messages):
        """Decide la respuesta según el último mensaje.

        :param messages: Conversación con ``role`` y ``content``
        :type messages: list[dict]
        :return: Respuesta JSON y conteo aproximado de tokens
        :rtype: ModelReply
        """
        last = str(messages[-1]["content"]) if messages else ""
        text = json.dumps(self._decide(last), ensure_ascii=False)
        input_tokens = sum(_count_words(message["content"]) for message in messages)
        return ModelReply(
            text=text,
            input_tokens=input_tokens,
            output_tokens=_count_words(text),
            model=self.name,
            cached=False,
        )


def _strip_code_fences(text):
    """Quita los cercos de código Markdown que a veces agrega el modelo.

    :param text: Texto devuelto por el modelo
    :type text: str
    :return: Texto sin cercos ni espacios a los lados
    :rtype: str
    """
    return CODE_FENCE_PATTERN.sub("", text.strip()).strip()


def _parse_body(response):
    """Extrae texto y tokens del cuerpo de la respuesta del gateway.

    :param response: Respuesta HTTP del gateway
    :type response: httpx.Response
    :return: Texto, tokens de entrada y tokens de salida
    :rtype: tuple[str, int, int]
    :raises ModelUnavailableError: Si el cuerpo no tiene ``choices`` o ``usage``
    """
    try:
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        usage = body["usage"]
        input_tokens = int(usage["prompt_tokens"])
        output_tokens = int(usage["completion_tokens"])
    except (ValueError, KeyError, IndexError, TypeError) as error:
        raise ModelUnavailableError("respuesta incompleta del gateway") from error
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)
    return _strip_code_fences(content), input_tokens, output_tokens


class GatewayModel:
    """Modelo real de Workers AI a través de Cloudflare AI Gateway.

    :param name: Nombre del modelo en Workers AI
    :type name: str
    :param config: Configuración validada (cuenta, gateway, token y palancas)
    :type config: app.config.Config
    :param http_client: Cliente ``httpx`` inyectado
    :type http_client: httpx.Client
    """

    def __init__(self, name, config, http_client):
        self.name = name
        self._config = config
        self._http = http_client
        self._url = GATEWAY_URL_TEMPLATE.format(
            account=config.cf_account_id, gateway=config.cf_gateway_id
        )

    def _headers(self):
        """Arma los encabezados: token y, si aplica, la caché del gateway.

        :return: Encabezados de la petición
        :rtype: dict[str, str]
        """
        headers = {"Authorization": f"Bearer {self._config.cf_api_token}"}
        if self._config.cache_ttl_seconds > 0:
            headers[CACHE_TTL_HEADER] = str(self._config.cache_ttl_seconds)
        return headers

    def _payload(self, messages):
        """Arma el cuerpo con el mensaje de sistema y las palancas de costo.

        :param messages: Conversación con ``role`` y ``content``
        :type messages: list[dict]
        :return: Cuerpo JSON de la petición
        :rtype: dict
        """
        conversation = [{"role": "system", "content": SYSTEM_PROMPT}]
        conversation.extend(
            {"role": message["role"], "content": message["content"]}
            for message in messages
        )
        return {
            "model": self.name,
            "messages": conversation,
            "max_tokens": self._config.model_max_tokens,
            "temperature": self._config.model_temperature,
        }

    def complete(self, messages):
        """Llama al gateway y devuelve la respuesta del modelo.

        :param messages: Conversación con ``role`` y ``content``
        :type messages: list[dict]
        :return: Respuesta, tokens de ``usage`` y si salió de la caché
        :rtype: ModelReply
        :raises ModelUnavailableError: Si hay error de red, de tiempo, un estado
            distinto de 2xx o un cuerpo incompleto
        """
        try:
            response = self._http.post(
                self._url,
                json=self._payload(messages),
                headers=self._headers(),
                timeout=GATEWAY_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as error:
            raise ModelUnavailableError(type(error).__name__) from error
        if not response.is_success:
            raise ModelUnavailableError(f"estado {response.status_code}")
        cache_status = response.headers.get(CACHE_STATUS_HEADER, "")
        is_cached = cache_status.strip().upper() == CACHE_HIT
        return ModelReply(*_parse_body(response), self.name, is_cached)


def build_models(config, directory, http_client=None):
    """Construye los dos modelos con nombre que indica la configuración.

    :param config: Configuración validada
    :type config: app.config.Config
    :param directory: Directorio de empleados (aporta los departamentos)
    :type directory: app.directory.EmployeeDirectory
    :param http_client: Cliente ``httpx`` para ``gateway``; si falta, se crea
    :type http_client: httpx.Client or None
    :return: ``{config.model_small: modelo, config.model_large: modelo}``
    :rtype: dict[str, LanguageModel]
    :raises ValueError: Si el proveedor no está soportado
    """
    names = (config.model_small, config.model_large)
    if config.model_provider == "fake":
        departments = directory.departments()
        return {name: FakeModel(name, departments) for name in names}
    if config.model_provider == "gateway":
        client = http_client or httpx.Client()
        return {name: GatewayModel(name, config, client) for name in names}
    raise ValueError(f"MODEL_PROVIDER no soportado: {config.model_provider!r}")
