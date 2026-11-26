"""El modelo detrás de una interfaz: simulado o Cloudflare Workers AI.

También vive aquí lo que decide cuánto cuesta una llamada: precios y enrutamiento.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

from app.config import Settings
from app.directory import normalize
from app.tracing import traced

TOOL_RESULT_PREFIX = "Resultado de la herramienta: "
DRAFT_PREFIX = "Redacta"
REVISE_PREFIX = "Corrige"
FACTS_START = "HECHOS:"
FACTS_END = "FIN DE HECHOS"
FAKE_DEFAULT = "Pregúntame por un empleado (EMP-0001) o un departamento."
EMPLOYEE_ID = re.compile(r"EMP-\d{4}")
LARGE_KEYWORDS = ("compara", "resume", "explica", "por que", "analiza", "todos")
GATEWAY_URL = (
    "https://gateway.ai.cloudflare.com/v1/{account}/{gateway}"
    "/workers-ai/v1/chat/completions"
)
MILLION = 1_000_000


class ModelUnavailable(Exception):
    """El modelo real no respondió."""


@dataclass(frozen=True)
class Completion:
    """Respuesta de una llamada al modelo."""

    content: str
    input_tokens: int
    output_tokens: int
    model: str
    cached: bool = False


class Model(Protocol):
    """Lo único que un agente sabe del modelo."""

    def complete(self, messages: list[dict], model: str) -> Completion:
        """Completa una conversación con el modelo indicado."""


class Prices:
    """Precios por modelo, en USD por millón de tokens."""

    def __init__(self, models: dict):
        self._models = models

    @classmethod
    def from_file(cls, path: Path) -> "Prices":
        """Carga los precios.

        :param path: Archivo ``model_prices.json``
        :type path: pathlib.Path
        :return: Tabla de precios
        :rtype: Prices
        """
        return cls(json.loads(Path(path).read_text(encoding="utf-8"))["models"])

    def cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Costo de una llamada.

        :param model: Nombre del modelo
        :type model: str
        :param input_tokens: Tokens de entrada
        :type input_tokens: int
        :param output_tokens: Tokens de salida
        :type output_tokens: int
        :return: Costo en USD; 0 si el modelo no tiene precio
        :rtype: float
        """
        price = self._models.get(model, {"input": 0.0, "output": 0.0})
        total = input_tokens * price["input"] + output_tokens * price["output"]
        return total / MILLION


def choose_model(question: str, settings: Settings) -> tuple[str, str]:
    """Regla de enrutamiento: una regla en código, no otro modelo.

    :param question: Pregunta de la persona
    :type question: str
    :param settings: Configuración con los modelos y los umbrales
    :type settings: Settings
    :return: El modelo y el motivo de la decisión
    :rtype: tuple[str, str]
    """
    if not settings.routing:
        return settings.model_large, "routing_off"
    if len(question) > settings.router_max_chars:
        return settings.model_large, "long_question"
    plain = normalize(question)
    for keyword in LARGE_KEYWORDS:
        if keyword in plain:
            return settings.model_large, f"keyword:{keyword}"
    return settings.model_small, "simple_question"


def _words(text: str) -> int:
    return len(text.split())


def _json(reply: dict) -> str:
    return json.dumps(reply, ensure_ascii=False)


def _facts(message: str) -> list[str]:
    block = message.split(FACTS_START, 1)[-1].split(FACTS_END, 1)[0]
    return [line.strip("- ").strip() for line in block.splitlines() if line.strip()]


class FakeModel:
    """Modelo simulado: determinista, sin red y sin costo real.

    Decide con reglas sobre el último mensaje. Cuenta tokens por palabras, y el
    costo se calcula con el precio del nombre de modelo que se le pide.
    """

    def __init__(self, departments: list[str]):
        self._departments = departments

    def _reply(self, last: str) -> str:
        if last.startswith(TOOL_RESULT_PREFIX):
            result = last[len(TOOL_RESULT_PREFIX):]
            return _json({"answer": f"Según el directorio: {result}"})
        if last.startswith(DRAFT_PREFIX):
            # El primer borrador sale incompleto a propósito: así se prueba la crítica
            return _facts(last)[0]
        if last.startswith(REVISE_PREFIX):
            return " ".join(_facts(last))
        employee_id = EMPLOYEE_ID.search(last)
        if employee_id:
            wants_vacations = "vacacion" in normalize(last)
            tool = "get_vacation_balance" if wants_vacations else "get_employee"
            return _json(
                {
                    "thought": f"Necesito la herramienta {tool}.",
                    "tool": tool,
                    "args": {"employee_id": employee_id.group()},
                }
            )
        plain = normalize(last)
        for department in self._departments:
            if normalize(department) in plain:
                return _json(
                    {
                        "thought": "Necesito la lista del departamento.",
                        "tool": "search_by_department",
                        "args": {"department": department},
                    }
                )
        return _json({"answer": FAKE_DEFAULT})

    def complete(self, messages: list[dict], model: str) -> Completion:
        """Responde según las reglas del modelo simulado.

        :param messages: Conversación completa
        :type messages: list[dict]
        :param model: Nombre con el que se cobra la llamada
        :type model: str
        :return: Respuesta determinista con tokens contados por palabras
        :rtype: Completion
        """
        content = self._reply(messages[-1]["content"])
        input_tokens = sum(_words(message["content"]) for message in messages)
        return Completion(content, input_tokens, _words(content), model)


class GatewayModel:
    """Cloudflare Workers AI a través de AI Gateway."""

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self._settings = settings
        self._client = client or httpx.Client(timeout=settings.model_timeout_seconds)
        self._url = GATEWAY_URL.format(
            account=settings.cf_account_id, gateway=settings.cf_gateway_id
        )

    def _headers(self) -> dict:
        settings = self._settings
        headers = {"Authorization": f"Bearer {settings.cf_api_token}"}
        if settings.cf_aig_token:
            headers["cf-aig-authorization"] = f"Bearer {settings.cf_aig_token}"
        if settings.cache_ttl_seconds > 0:
            headers["cf-aig-cache-ttl"] = str(settings.cache_ttl_seconds)
        else:
            headers["cf-aig-skip-cache"] = "true"
        return headers

    def complete(self, messages: list[dict], model: str) -> Completion:
        """Llama al modelo real.

        :param messages: Conversación completa
        :type messages: list[dict]
        :param model: Modelo de Workers AI
        :type model: str
        :return: Respuesta con los tokens que reporta el proveedor
        :rtype: Completion
        :raises ModelUnavailable: Si la llamada falla; el error no lleva el token
        """
        body = {
            "model": model,
            "messages": messages,
            "max_tokens": self._settings.model_max_tokens,
            "temperature": self._settings.model_temperature,
        }
        try:
            response = self._client.post(self._url, json=body, headers=self._headers())
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"] or ""
            usage = data.get("usage") or {}
        except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError) as error:
            status = getattr(getattr(error, "response", None), "status_code", None)
            raise ModelUnavailable(f"{type(error).__name__} status={status}") from None
        cached = response.headers.get("cf-aig-cache-status", "").upper() == "HIT"
        return Completion(
            content,
            int(usage.get("prompt_tokens", 0)),
            int(usage.get("completion_tokens", 0)),
            model,
            cached,
        )


@dataclass
class Usage:
    """Lo que lleva gastado una corrida de agente."""

    steps: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    cached_calls: int = 0


class ModelCaller:
    """Llama al modelo, lo traza y lleva la cuenta de tokens y costo."""

    def __init__(self, model: Model, prices: Prices):
        self._model = model
        self._prices = prices

    @traced("model_call", run_type="llm")
    def _traced_call(self, messages: list[dict], model: str) -> dict:
        completion = self._model.complete(messages, model)
        return {
            "completion": completion,
            "content": completion.content,
            "usage_metadata": {
                "input_tokens": completion.input_tokens,
                "output_tokens": completion.output_tokens,
                "total_tokens": completion.input_tokens + completion.output_tokens,
            },
            "ls_model_name": model,
        }

    def call(self, messages: list[dict], model: str, usage: Usage) -> str:
        """Hace una llamada y la suma a ``usage``.

        :param messages: Conversación completa
        :type messages: list[dict]
        :param model: Modelo a usar
        :type model: str
        :param usage: Acumulado de la corrida; se actualiza
        :type usage: Usage
        :return: El texto que respondió el modelo
        :rtype: str
        """
        completion = self._traced_call(messages, model)["completion"]
        usage.steps += 1
        usage.input_tokens += completion.input_tokens
        usage.output_tokens += completion.output_tokens
        if completion.cached:
            usage.cached_calls += 1
        else:
            usage.cost_usd += self._prices.cost(
                model, completion.input_tokens, completion.output_tokens
            )
        return completion.content
