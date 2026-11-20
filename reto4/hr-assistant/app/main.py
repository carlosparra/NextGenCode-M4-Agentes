"""API web sin estado del HR Assistant (ADR 0001, 0004 a 0007, 0009 y 0010).

``POST /ask`` y ``GET /metrics`` exigen ``X-API-Key``; ``/``, ``/health`` y
``/docs`` son públicas. El log lleva el nombre del cliente, nunca su clave.
"""

import os
import uuid
from pathlib import Path
from typing import List, Literal

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator

from app.agent import Agent
from app.auth import KeyRing, build_require_client
from app.config import ConfigError, load_config
from app.directory import load_directory
from app.llm import ModelUnavailableError, build_models
from app.observability import build_observability
from app.pii import mask_pii
from app.pricing import load_prices
from app.ratelimit import RateLimiter
from app.router import choose_model

STATIC_DIR = Path(__file__).resolve().parent / "static"
PRODUCT_ROOT = Path(__file__).resolve().parent.parent
REQUEST_ID_HEADER = "X-Request-ID"
MILLISECONDS_PER_SECOND = 1000


class HistoryMessage(BaseModel):
    """Mensaje previo de la conversación enviado por el cliente.

    :param role: ``user`` o ``assistant``
    :type role: str
    :param content: Texto del mensaje
    :type content: str
    """

    role: Literal["user", "assistant"]
    content: str


class AskResponse(BaseModel):
    """Respuesta de ``POST /ask``.

    :param answer: Respuesta del agente
    :type answer: str
    :param steps: Llamadas hechas al modelo
    :type steps: int
    :param tools_used: Herramientas usadas
    :type tools_used: list[str]
    :param input_tokens: Tokens de entrada
    :type input_tokens: int
    :param output_tokens: Tokens de salida
    :type output_tokens: int
    :param request_id: Id de la petición
    :type request_id: str
    :param model: Modelo que respondió
    :type model: str
    :param route: Motivo del enrutador
    :type route: str
    :param cached_calls: Llamadas que salieron de la caché del gateway
    :type cached_calls: int
    :param cost_usd: Costo de la respuesta en USD
    :type cost_usd: float
    """

    answer: str
    steps: int
    tools_used: List[str]
    input_tokens: int
    output_tokens: int
    request_id: str
    model: str
    route: str
    cached_calls: int
    cost_usd: float


def _build_request_model(max_question_chars):
    """Crea el modelo de petición con el largo máximo configurado.

    :param max_question_chars: Largo máximo de la pregunta
    :type max_question_chars: int
    :return: Clase Pydantic de la petición
    :rtype: type
    """

    class AskRequest(BaseModel):
        """Cuerpo de ``POST /ask``."""

        question: str = Field(max_length=max_question_chars)
        history: List[HistoryMessage] = Field(default_factory=list)

        @field_validator("question")
        @classmethod
        def _not_blank(cls, value):
            """Rechaza preguntas vacías o solo con espacios.

            :param value: Pregunta recibida
            :type value: str
            :return: La pregunta sin cambios
            :rtype: str
            :raises ValueError: Si la pregunta está vacía
            """
            if not value.strip():
                raise ValueError("question must not be empty")
            return value

    return AskRequest


def _check_models(config, models, prices):
    """Revisa que ``MODEL_SMALL`` y ``MODEL_LARGE`` existan y tengan precio.

    :param config: Configuración validada
    :type config: app.config.Config
    :param models: Modelos por nombre
    :type models: dict
    :param prices: Tabla de precios
    :type prices: app.pricing.PriceTable
    :raises ConfigError: Si falta un modelo o su precio
    """
    for name in (config.model_small, config.model_large):
        if name not in models:
            raise ConfigError(f"No hay modelo construido para {name!r}.")
        if not prices.has(name):
            raise ConfigError(f"El modelo {name!r} no tiene precio en PRICES_PATH.")


def _error_response(status, detail, request_id):
    """Arma una respuesta de error con ``request_id``.

    :param status: Código HTTP
    :type status: int
    :param detail: Detalle corto del error
    :type detail: str
    :param request_id: Id de la petición
    :type request_id: str
    :return: Respuesta JSON
    :rtype: fastapi.responses.JSONResponse
    """
    return JSONResponse(
        status_code=status,
        content={"detail": detail, "request_id": request_id},
    )


def _log_run(  # pylint: disable=too-many-arguments
    logger, request_id, request, result, route, *, client
):
    """Registra ``audit`` por herramienta y ``agent_run``, sin textos.

    :param logger: Logger de eventos JSON
    :type logger: app.observability.JsonLogger
    :param request_id: Id de la petición
    :type request_id: str
    :param request: Petición validada
    :type request: pydantic.BaseModel
    :param result: Resultado del agente
    :type result: app.agent.AgentResult
    :param route: Motivo del enrutador
    :type route: str
    :param client: Nombre del cliente (nunca su clave)
    :type client: str
    """
    for call in result.tool_calls:
        logger.log(
            "audit", request_id, client=client, action="tool_call",
            tool=call["tool"], args=call["args"],
        )
    logger.log(
        "agent_run", request_id,
        client=client,
        question_chars=len(request.question),
        history_messages=len(request.history),
        steps=result.steps,
        tools=list(result.tools_used),
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        stopped=result.stopped,
        model=result.model,
        route=route,
        cached_calls=result.cached_calls,
        cost_usd=result.cost_usd,
    )


def _mask_request(request):
    """Enmascara la PII de la pregunta y del historial antes de usarlos.

    :param request: Petición validada con ``question`` e ``history``
    :type request: pydantic.BaseModel
    :return: Pregunta enmascarada, historial enmascarado como lista de
        ``{"role", "content"}`` y conteo de tipos de PII encontrados
    :rtype: tuple[str, list[dict], collections.Counter]
    """
    question, found = mask_pii(request.question)
    history = []
    for message in request.history:
        content, history_found = mask_pii(message.content)
        found += history_found
        history.append({"role": message.role, "content": content})
    return question, history, found


def _log_pii(logger, request_id, client, found, answer_found):
    """Registra en la auditoría los tipos de PII enmascarados, sin valores.

    :param logger: Logger de eventos JSON
    :type logger: app.observability.JsonLogger
    :param request_id: Id de la petición
    :type request_id: str
    :param client: Nombre del cliente
    :type client: str
    :param found: Tipos encontrados en la pregunta y el historial
    :type found: collections.Counter
    :param answer_found: Tipos encontrados en la respuesta
    :type answer_found: collections.Counter
    """
    if found or answer_found:
        logger.log(
            "audit", request_id, client=client, action="pii_masked",
            input=dict(found), output=dict(answer_found),
        )


def _add_middleware(application, observability):
    """Agrega el middleware de ``X-Request-ID``, del evento ``request`` y del 500.

    :param application: App FastAPI
    :type application: fastapi.FastAPI
    :param observability: Reloj, logger y métricas
    :type observability: app.observability.Observability
    """
    clock = observability.clock
    logger = observability.logger

    @application.middleware("http")
    async def request_context(request: Request, call_next):
        """Asigna el id, mide la latencia y convierte errores en 500."""
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        request.state.request_id = request_id
        started = clock.monotonic()
        try:
            response = await call_next(request)
        except Exception as error:  # pylint: disable=broad-exception-caught
            logger.log("error", request_id, error_type=type(error).__name__)
            response = _error_response(500, "internal error", request_id)
        latency_ms = (clock.monotonic() - started) * MILLISECONDS_PER_SECOND
        response.headers[REQUEST_ID_HEADER] = request_id
        observability.metrics.record_request(response.status_code, latency_ms)
        logger.log(
            "request", request_id, method=request.method, path=request.url.path,
            status=response.status_code, latency_ms=round(latency_ms, 3),
            client=getattr(request.state, "client", None),
        )
        return response

    @application.exception_handler(ModelUnavailableError)
    async def model_unavailable(request: Request, error):
        """Traduce la falla del modelo real a ``502 model unavailable``."""
        request_id = request.state.request_id
        logger.log("error", request_id, error_type=type(error).__name__)
        return _error_response(502, "model unavailable", request_id)


def create_app(  # pylint: disable=too-many-arguments
    config, models, directory, prices, observability=None, *, rate_limiter=None
):
    """Construye la app FastAPI con sus dependencias ya creadas.

    :param config: Configuración validada
    :type config: app.config.Config
    :param models: Modelos por nombre (``MODEL_SMALL`` y ``MODEL_LARGE``)
    :type models: dict[str, app.llm.LanguageModel]
    :param directory: Directorio de empleados
    :type directory: app.directory.EmployeeDirectory
    :param prices: Tabla de precios por modelo
    :type prices: app.pricing.PriceTable
    :param observability: Reloj, logger, métricas y tracer; por omisión los
        reales
    :type observability: app.observability.Observability or None
    :param rate_limiter: Límite por cliente; por omisión uno con
        ``RATE_LIMIT_PER_MINUTE`` y el reloj de ``observability``
    :type rate_limiter: app.ratelimit.RateLimiter or None
    :return: La aplicación web
    :rtype: fastapi.FastAPI
    :raises ConfigError: Si ``MODEL_SMALL`` o ``MODEL_LARGE`` no tienen precio,
        o si las trazas están encendidas y falta ``langsmith``
    """
    _check_models(config, models, prices)
    observability = observability or build_observability(config)
    rate_limiter = rate_limiter or RateLimiter(
        config.rate_limit_per_minute, observability.clock
    )
    require_client = build_require_client(KeyRing(config.api_keys), rate_limiter)
    application = FastAPI(title="HR Assistant")
    ask_request = _build_request_model(config.max_question_chars)
    page = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    _add_middleware(application, observability)

    @application.get("/", response_class=HTMLResponse)
    def index():
        """Sirve la página web."""
        return HTMLResponse(page)

    @application.get("/health")
    def health():
        """Informa el estado y el id del proceso."""
        return {"status": "ok", "pid": os.getpid()}

    @application.get("/metrics", dependencies=[Depends(require_client)])
    def metrics():
        """Devuelve las métricas de este proceso; exige ``X-API-Key``."""
        return observability.metrics.snapshot(os.getpid())

    @application.post("/ask", response_model=AskResponse)
    def ask(
        request: ask_request, http_request: Request,
        client: str = Depends(require_client),
    ):
        """Responde una pregunta con el modelo que elige el enrutador.

        La clave se valida antes que el cuerpo: sin clave la respuesta es
        ``401`` aunque la pregunta sea inválida.
        """
        request_id = http_request.state.request_id
        model_name, route = choose_model(request.question, config)
        agent = Agent(
            models[model_name], directory, config.agent_max_steps,
            prices=prices, history_window=config.history_window,
            tracer=observability.tracer, request_id=request_id, client=client,
        )
        question, history, found = _mask_request(request)
        result = agent.run(question, history)
        result.answer, answer_found = mask_pii(result.answer)
        _log_pii(observability.logger, request_id, client, found, answer_found)
        _log_run(
            observability.logger, request_id, request, result, route,
            client=client,
        )
        observability.metrics.record_run(
            result.input_tokens, result.output_tokens, result.cost_usd
        )
        return AskResponse(
            answer=result.answer,
            steps=result.steps,
            tools_used=list(result.tools_used),
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            request_id=request_id,
            model=result.model or model_name,
            route=route,
            cached_calls=result.cached_calls,
            cost_usd=result.cost_usd,
        )

    return application


def _resolve_data_path(path):
    """Resuelve la ruta de datos; si es relativa y no existe, usa ``product/``.

    :param path: Ruta configurada (``EMPLOYEES_PATH`` o ``PRICES_PATH``)
    :type path: str
    :return: Ruta a usar para cargar el archivo
    :rtype: pathlib.Path
    """
    candidate = Path(path)
    if candidate.is_absolute() or candidate.exists():
        return candidate
    return PRODUCT_ROOT / candidate


def _build_default_app():
    """Construye la app a partir de ``os.environ``; falla si algo es inválido.

    :return: La aplicación web
    :rtype: fastapi.FastAPI
    :raises app.config.ConfigError: Si la configuración es inválida
    """
    config = load_config(os.environ)
    directory = load_directory(_resolve_data_path(config.employees_path))
    prices = load_prices(_resolve_data_path(config.prices_path))
    models = build_models(config, directory)
    return create_app(config, models, directory, prices)


app = _build_default_app()
