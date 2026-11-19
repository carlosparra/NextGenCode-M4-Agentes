"""API web sin estado del HR Assistant.

``create_app`` recibe sus dependencias para que las pruebas inyecten las suyas.
El modulo expone ``app`` para ``uvicorn app.main:app``.

Cada peticion recibe un ``request_id`` (del encabezado ``X-Request-ID`` si es
valido o un UUID nuevo), deja un evento ``request`` en el log JSON y alimenta
las metricas de ``GET /metrics``.

Cada pregunta se enruta a ``MODEL_SMALL`` o ``MODEL_LARGE`` y la respuesta dice
que modelo uso, por que y cuanto costo.

``POST /ask`` y ``GET /metrics`` exigen ``X-API-Key`` y respetan el limite de
peticiones por cliente; con ``ENVIRONMENT=production`` la aplicacion no arranca
si la configuracion no cumple las reglas de ``app.compliance``.
"""

import os
import re
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field, field_validator

from app import compliance
from app.agent import Agent
from app.auth import ApiKeyAuthenticator
from app.clock import Clock, SystemClock
from app.config import Settings, load_settings
from app.directory import EmployeeDirectory
from app.gateway import ModelUnavailable
from app.llm import LLM, build_models
from app.metrics import Metrics
from app.pricing import PriceTable
from app.ratelimit import RateLimiter
from app.router import route
from app.telemetry import JsonLogger
from app.tracing import build_tracer

STATIC_DIR = Path(__file__).resolve().parent / "static"
API_KEY_HEADER = "X-API-Key"
UNAUTHORIZED_STATUS = 401
UNAUTHORIZED_DETAIL = "invalid or missing API key"
RATE_LIMITED_STATUS = 429
RATE_LIMITED_DETAIL = "rate limit exceeded"
RETRY_AFTER_HEADER = "Retry-After"
REQUEST_ID_HEADER = "X-Request-ID"
REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,128}")
METRICS_PATH = "/metrics"
INTERNAL_ERROR_STATUS = 500
INTERNAL_ERROR_DETAIL = "internal error"
MODEL_UNAVAILABLE_STATUS = 502
MODEL_UNAVAILABLE_DETAIL = "model unavailable"
MILLISECONDS = 1000
LATENCY_DECIMALS = 3


class AskResponse(BaseModel):
    """Respuesta de ``POST /ask``.

    ``model``, ``route``, ``cached_calls`` y ``cost_usd`` se omiten solo cuando
    se inyecta un modelo sin nombre (``create_app(llm=...)``): sin nombre no
    hay precio.
    """

    answer: str
    steps: int
    tools_used: list[str]
    input_tokens: int
    output_tokens: int
    request_id: str
    model: str | None = None
    route: str | None = None
    cached_calls: int | None = None
    cost_usd: float | None = None


class HealthResponse(BaseModel):
    """Respuesta de ``GET /health``."""

    status: str
    pid: int


@dataclass(frozen=True)
class AppDependencies:  # pylint: disable=too-many-instance-attributes
    """Dependencias ya construidas de la aplicacion.

    :param settings: Configuracion validada
    :type settings: app.config.Settings
    :param models: Modelo por nombre (``MODEL_SMALL`` y ``MODEL_LARGE``)
    :type models: dict[str, app.llm.LLM]
    :param prices: Tabla de precios por modelo
    :type prices: app.pricing.PriceTable
    :param report_cost: Si la respuesta lleva modelo, motivo y costo
    :type report_cost: bool
    :param directory: Directorio de empleados
    :type directory: app.directory.EmployeeDirectory
    :param clock: Reloj para la hora del log y las latencias
    :type clock: app.clock.Clock
    :param logger: Log JSON de una linea por evento
    :type logger: app.telemetry.JsonLogger
    :param metrics: Metricas de este proceso
    :type metrics: app.metrics.Metrics
    :param tracer: Trazador de corridas, modelo y herramientas
    :type tracer: object
    :param authenticator: Identifica al cliente por su clave
    :type authenticator: app.auth.ApiKeyAuthenticator
    :param rate_limiter: Limite de peticiones por cliente
    :type rate_limiter: app.ratelimit.RateLimiter
    """

    settings: Settings
    models: dict
    prices: PriceTable
    report_cost: bool
    directory: EmployeeDirectory
    clock: Clock
    logger: JsonLogger
    metrics: Metrics
    tracer: object
    authenticator: ApiKeyAuthenticator
    rate_limiter: RateLimiter


def _not_blank(value: str) -> str:
    """Rechaza textos vacios o formados solo por espacios.

    :param value: Texto a validar
    :type value: str
    :return: El mismo texto
    :rtype: str
    :raises ValueError: Si el texto esta vacio tras quitar espacios
    """
    if not value.strip():
        raise ValueError("must not be empty or whitespace")
    return value


def build_request_models(max_chars: int):
    """Construye los modelos de peticion con el largo maximo configurado.

    :param max_chars: Largo maximo de la pregunta y de cada mensaje del historial
    :type max_chars: int
    :return: Las clases ``(HistoryMessage, AskRequest)``
    :rtype: tuple[type, type]
    """

    class HistoryMessage(BaseModel):
        """Mensaje previo de la conversacion enviado por el cliente."""

        role: Literal["user", "assistant"]
        content: str = Field(max_length=max_chars)

    class AskRequest(BaseModel):
        """Cuerpo de ``POST /ask``."""

        question: str = Field(min_length=1, max_length=max_chars)
        history: list[HistoryMessage] = Field(default_factory=list)

        @field_validator("question")
        @classmethod
        def question_not_blank(cls, value: str) -> str:
            """Rechaza preguntas vacias o solo con espacios.

            :param value: Pregunta recibida
            :type value: str
            :return: La pregunta sin cambios
            :rtype: str
            """
            return _not_blank(value)

    return HistoryMessage, AskRequest


def resolve_request_id(header_value) -> str:
    """Usa el id del cliente si es valido; si no, genera un UUID4.

    Solo se aceptan letras, digitos y ``._:-`` (1 a 128), para que el id no
    pueda inyectar saltos de linea ni texto largo en el log.

    :param header_value: Valor de ``X-Request-ID`` o ``None``
    :type header_value: str or None
    :return: El id de la peticion
    :rtype: str
    """
    if header_value and REQUEST_ID_PATTERN.fullmatch(header_value):
        return header_value
    return str(uuid.uuid4())


def _add_observability_middleware(application: FastAPI, deps: AppDependencies):
    """Agrega el middleware de ``request_id``, latencia, log, metricas y errores.

    :param application: Aplicacion a la que se agrega el middleware
    :type application: fastapi.FastAPI
    :param deps: Dependencias de la aplicacion
    :type deps: AppDependencies
    """

    @application.middleware("http")
    async def observe(request: Request, call_next):
        """Asigna el id, mide la peticion y convierte errores en un 500 generico.

        :param request: Peticion entrante
        :type request: fastapi.Request
        :param call_next: Siguiente manejador de la cadena
        :type call_next: callable
        :return: La respuesta con el encabezado ``X-Request-ID``
        :rtype: starlette.responses.Response
        """
        request_id = resolve_request_id(request.headers.get(REQUEST_ID_HEADER))
        request.state.request_id = request_id
        log = deps.logger.bind(request_id)
        started = deps.clock.monotonic()
        # Cualquier excepcion se registra solo con su tipo y no expone detalles.
        try:
            response = await call_next(request)
        except Exception as error:  # pylint: disable=broad-exception-caught
            log.error(error_type=type(error).__name__)
            response = JSONResponse(
                status_code=INTERNAL_ERROR_STATUS,
                content={"detail": INTERNAL_ERROR_DETAIL, "request_id": request_id},
            )
        elapsed = deps.clock.monotonic() - started
        latency_ms = round(elapsed * MILLISECONDS, LATENCY_DECIMALS)
        response.headers[REQUEST_ID_HEADER] = request_id
        path = request.url.path
        if path != METRICS_PATH:
            deps.metrics.record_request(
                status=response.status_code, latency_ms=latency_ms
            )
        # El cliente lo deja ``require_client``; sin autenticacion queda None.
        client = getattr(request.state, "client", None)
        deps.logger.bind(request_id, client).request(
            method=request.method,
            path=path,
            status=response.status_code,
            latency_ms=latency_ms,
        )
        return response


def build_client_dependency(deps: AppDependencies):
    """Construye la dependencia que autentica y limita cada peticion protegida.

    Va como dependencia de la ruta para que la clave se revise antes que los
    campos del cuerpo (401 antes que 422).

    :param deps: Dependencias de la aplicacion
    :type deps: AppDependencies
    :return: Funcion ``require_client`` para ``fastapi.Depends``
    :rtype: callable
    """
    api_key_scheme = APIKeyHeader(name=API_KEY_HEADER, auto_error=False)

    def require_client(
        request: Request, api_key: str | None = Security(api_key_scheme)
    ) -> str:
        """Devuelve el cliente dueno de la clave o corta la peticion.

        :param request: Peticion entrante; guarda el cliente en ``state``
        :type request: fastapi.Request
        :param api_key: Valor de ``X-API-Key`` o ``None``
        :type api_key: str or None
        :return: Nombre del cliente
        :rtype: str
        :raises fastapi.HTTPException: 401 sin clave o con una invalida; 429
            con ``Retry-After`` si el cliente paso su limite
        """
        client = deps.authenticator.authenticate(api_key)
        if client is None:
            raise HTTPException(
                status_code=UNAUTHORIZED_STATUS, detail=UNAUTHORIZED_DETAIL
            )
        request.state.client = client
        decision = deps.rate_limiter.check(client)
        if not decision.allowed:
            raise HTTPException(
                status_code=RATE_LIMITED_STATUS,
                detail=RATE_LIMITED_DETAIL,
                headers={RETRY_AFTER_HEADER: str(decision.retry_after)},
            )
        return client

    return require_client


def _add_routes(application: FastAPI, deps: AppDependencies, page: str):
    """Registra las rutas de la API.

    :param application: Aplicacion donde se registran las rutas
    :type application: fastapi.FastAPI
    :param deps: Dependencias de la aplicacion
    :type deps: AppDependencies
    :param page: HTML de la pagina web
    :type page: str
    """
    settings = deps.settings
    _, ask_request = build_request_models(settings.max_question_chars)
    require_client = build_client_dependency(deps)

    @application.get("/", response_class=HTMLResponse)
    def home() -> HTMLResponse:
        """Sirve la pagina web."""
        return HTMLResponse(page)

    @application.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        """Informa que el proceso esta vivo y su id."""
        return HealthResponse(status="ok", pid=os.getpid())

    @application.get(METRICS_PATH, dependencies=[Depends(require_client)])
    def metrics() -> dict:
        """Devuelve las metricas de este proceso (exige clave)."""
        return deps.metrics.snapshot(slo_p95_ms=settings.slo_p95_ms)

    @application.post(
        "/ask", response_model=AskResponse, response_model_exclude_none=True
    )
    def ask(
        payload: ask_request,
        request: Request,
        client: str = Depends(require_client),
    ) -> AskResponse:
        """Enruta la pregunta y la responde; el agente se crea por peticion."""
        request_id = request.state.request_id
        chosen = route(payload.question, settings)
        agent = Agent(
            llm=deps.models[chosen.model],
            directory=deps.directory,
            max_steps=settings.agent_max_steps,
            telemetry=deps.logger.bind(request_id, client),
            tracer=deps.tracer,
            model=chosen.model,
            route=chosen.reason,
            history_window=settings.history_window,
            prices=deps.prices,
        )
        history = [message.model_dump() for message in payload.history]
        result = agent.run(payload.question, history)
        deps.metrics.add_tokens(
            input_tokens=result.input_tokens, output_tokens=result.output_tokens
        )
        response = AskResponse(
            answer=result.answer,
            steps=result.steps,
            tools_used=result.tools_used,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            request_id=request_id,
        )
        if not deps.report_cost:
            return response
        deps.metrics.add_cost(result.cost_usd)
        return response.model_copy(
            update={
                "model": result.model,
                "route": chosen.reason,
                "cached_calls": result.cached_calls,
                "cost_usd": result.cost_usd,
            }
        )


def _add_error_handlers(application: FastAPI, deps: AppDependencies):
    """Convierte la falla del modelo real en un 502 generico.

    :param application: Aplicacion donde se registra el manejador
    :type application: fastapi.FastAPI
    :param deps: Dependencias de la aplicacion
    :type deps: AppDependencies
    """

    @application.exception_handler(ModelUnavailable)
    async def model_unavailable(request: Request, error: ModelUnavailable):
        """Registra el error solo con su tipo y responde 502.

        :param request: Peticion que fallo
        :type request: fastapi.Request
        :param error: Falla del gateway
        :type error: app.gateway.ModelUnavailable
        :return: ``502 {"detail": "model unavailable", "request_id": ...}``
        :rtype: fastapi.responses.JSONResponse
        """
        request_id = request.state.request_id
        deps.logger.bind(request_id).error(error_type=type(error).__name__)
        return JSONResponse(
            status_code=MODEL_UNAVAILABLE_STATUS,
            content={"detail": MODEL_UNAVAILABLE_DETAIL, "request_id": request_id},
        )


def _build_models(settings, directory, llm, http_client) -> tuple[dict, bool]:
    """Arma el modelo por nombre y decide si se reporta el costo.

    Si se inyecta un ``llm`` (pruebas de sesiones previas), se usa para los
    dos nombres y no se reporta costo: no se sabe que modelo es.

    :param settings: Configuracion validada
    :type settings: app.config.Settings
    :param directory: Directorio de empleados
    :type directory: app.directory.EmployeeDirectory
    :param llm: Modelo inyectado o ``None``
    :type llm: app.llm.LLM or None
    :param http_client: Cliente HTTP para el gateway o ``None``
    :type http_client: httpx.Client or None
    :return: Modelo por nombre y si se reporta el costo
    :rtype: tuple[dict[str, app.llm.LLM], bool]
    """
    if llm is not None:
        return {settings.model_small: llm, settings.model_large: llm}, False
    return build_models(settings, directory, http_client), True


def create_app(  # pylint: disable=too-many-arguments
    settings: Settings | None = None,
    llm: LLM | None = None,
    directory: EmployeeDirectory | None = None,
    *,
    clock: Clock | None = None,
    log_stream=None,
    metrics: Metrics | None = None,
    tracer=None,
    http_client=None,
    rate_limiter: RateLimiter | None = None,
) -> FastAPI:
    """Crea la aplicacion FastAPI con sus dependencias.

    Las dependencias que falten se construyen a partir del entorno. Antes de
    construir nada se aplican las reglas de compliance.

    :param settings: Configuracion; por omision se lee de ``os.environ``
    :type settings: Settings or None
    :param llm: Modelo unico para los dos nombres (sin reporte de costo); por
        omision los dos modelos que indica ``MODEL_PROVIDER``
    :type llm: LLM or None
    :param directory: Directorio de empleados; por omision ``EMPLOYEES_PATH``
    :type directory: EmployeeDirectory or None
    :param clock: Reloj; por omision el del sistema
    :type clock: app.clock.Clock or None
    :param log_stream: Destino del log JSON; por omision ``sys.stdout``
    :type log_stream: typing.TextIO or None
    :param metrics: Metricas del proceso; por omision unas nuevas
    :type metrics: app.metrics.Metrics or None
    :param tracer: Trazador; por omision el que indique la configuracion
    :type tracer: object or None
    :param http_client: Cliente HTTP del gateway; por omision uno con tiempo
        limite (en pruebas, uno con transporte falso)
    :type http_client: httpx.Client or None
    :param rate_limiter: Limite por cliente con su reloj ya inyectado; por
        omision ``RATE_LIMIT_PER_MINUTE`` con el reloj del sistema
    :type rate_limiter: app.ratelimit.RateLimiter or None
    :return: La aplicacion lista para servir
    :rtype: fastapi.FastAPI
    :raises app.config.ConfigError: Si la configuracion del entorno es invalida
        o, en produccion, insegura
    """
    if settings is None:
        settings = load_settings(os.environ)
    compliance.enforce(settings)
    if directory is None:
        directory = EmployeeDirectory(settings.employees_path)
    clock = clock if clock is not None else SystemClock()
    stream = log_stream if log_stream is not None else sys.stdout
    models, report_cost = _build_models(settings, directory, llm, http_client)
    deps = AppDependencies(
        settings=settings,
        models=models,
        prices=PriceTable.load(settings.prices_path),
        report_cost=report_cost,
        directory=directory,
        clock=clock,
        logger=JsonLogger(stream, clock, settings.service_name),
        metrics=metrics if metrics is not None else Metrics(),
        tracer=tracer if tracer is not None else build_tracer(settings),
        authenticator=ApiKeyAuthenticator(settings.api_keys),
        # El limite lleva su propio reloj: asi no altera las lecturas del reloj
        # de latencias. Su reloj se inyecta con ``rate_limiter``.
        rate_limiter=(
            rate_limiter
            if rate_limiter is not None
            else RateLimiter(settings.rate_limit_per_minute, SystemClock())
        ),
    )
    page = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    application = FastAPI(title="HR Assistant")
    _add_observability_middleware(application, deps)
    _add_error_handlers(application, deps)
    _add_routes(application, deps, page)
    return application


app = create_app()
