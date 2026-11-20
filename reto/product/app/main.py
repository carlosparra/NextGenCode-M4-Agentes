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

La API se documenta en ``/docs`` y ``/openapi.json`` (publicos, sin claves):
version ``APP_VERSION``, tags ``chat`` y ``operations``, errores de
``POST /ask`` con ejemplo y el esquema ``X-API-Key``. Todo estado compartido
del proceso (metricas, limite, cache, log) vive detras de un ``threading.Lock``.

Con ``RESPONSE_CACHE_TTL_SECONDS`` mayor que 0, una pregunta repetida se
responde desde ``app.cache`` sin llamar al modelo (``cache: "hit"``).

Orden de las guardas de ``POST /ask``: clave (401), limite (429), esquema
(422), inyeccion (400), datos sensibles (``app.pii``), cache, agente y
validacion de la salida (``app.guardrails``).
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

from app import cache as response_cache
from app import compliance
from app.agent import Agent, CostOptions
from app.auth import ApiKeyAuthenticator
from app.cache import CACHE_HIT, CACHE_MISS, CachedAnswer, ResponseCache
from app.clock import Clock, SystemClock
from app.config import Settings, load_settings
from app.directory import EmployeeDirectory
from app.gateway import ModelUnavailable
from app.guardrails import GuardedInput, InputRejected, RequestGuard
from app.llm import LLM, build_models
from app.metrics import SECURITY_AUTH_FAILURES, SECURITY_RATE_LIMITED, Metrics
from app.pricing import PriceTable
from app.ratelimit import RateLimiter
from app.router import route
from app.telemetry import AUDIT_AUTH_FAILED, AUDIT_RATE_LIMITED, JsonLogger
from app.tracing import build_tracer

STATIC_DIR = Path(__file__).resolve().parent / "static"
API_KEY_HEADER = "X-API-Key"
UNAUTHORIZED_STATUS = 401
UNAUTHORIZED_DETAIL = "invalid or missing API key"
RATE_LIMITED_STATUS = 429
RATE_LIMITED_DETAIL = "rate limit exceeded"
RETRY_AFTER_HEADER = "Retry-After"
INPUT_REJECTED_STATUS = 400
REQUEST_ID_HEADER = "X-Request-ID"
REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,128}")
METRICS_PATH = "/metrics"
INTERNAL_ERROR_STATUS = 500
INTERNAL_ERROR_DETAIL = "internal error"
MODEL_UNAVAILABLE_STATUS = 502
MODEL_UNAVAILABLE_DETAIL = "model unavailable"
MILLISECONDS = 1000
LATENCY_DECIMALS = 3
ASK_PATH = "/ask"
# Lo que se guarda en ``request.state`` para que el middleware lo registre.
COST_STATE = "cost_usd"

API_TITLE = "HR Assistant API"
API_DESCRIPTION = (
    "Asistente de Recursos Humanos: responde preguntas sobre empleados con un "
    "agente de bucle acotado y herramientas de solo lectura. `POST /ask` y "
    "`GET /metrics` exigen el encabezado `X-API-Key` (boton Authorize). Cada "
    "respuesta trae `X-Request-ID` para rastrear la peticion en el log y en "
    "las trazas."
)
TAG_CHAT = "chat"
TAG_OPERATIONS = "operations"
OPENAPI_TAGS = [
    {"name": TAG_CHAT, "description": "Preguntas al asistente de RH."},
    {
        "name": TAG_OPERATIONS,
        "description": "Salud, metricas y pagina web del servicio.",
    },
]
API_KEY_DESCRIPTION = "Clave del cliente; se configura en `API_KEYS`."


class ErrorResponse(BaseModel):
    """Cuerpo de un error de la API."""

    detail: str


class ErrorWithRequestId(BaseModel):
    """Cuerpo de un error del servidor, con el id para soporte."""

    detail: str
    request_id: str


def _error_doc(description: str, example: dict, model=ErrorResponse) -> dict:
    """Documenta una respuesta de error para OpenAPI con un ejemplo de cuerpo.

    :param description: Cuando ocurre el error
    :type description: str
    :param example: Cuerpo de ejemplo
    :type example: dict
    :param model: Modelo del cuerpo, o ``None`` para no fijar esquema
    :type model: type or None
    :return: Entrada para el parametro ``responses`` de la ruta
    :rtype: dict
    """
    doc = {
        "description": description,
        "content": {"application/json": {"example": example}},
    }
    if model is not None:
        doc["model"] = model
    return doc


UNAUTHORIZED_DOC = _error_doc(
    "Falta `X-API-Key` o la clave no es valida.", {"detail": UNAUTHORIZED_DETAIL}
)
RATE_LIMITED_DOC = _error_doc(
    "El cliente paso su limite por minuto; `Retry-After` dice cuantos "
    "segundos esperar.",
    {"detail": RATE_LIMITED_DETAIL},
)
ASK_RESPONSES = {
    400: _error_doc(
        "Pregunta rechazada: inyeccion de instrucciones o datos sensibles con "
        "`PII_POLICY=block`.",
        {"detail": "input rejected"},
    ),
    UNAUTHORIZED_STATUS: UNAUTHORIZED_DOC,
    422: _error_doc(
        "El cuerpo no cumple el esquema: pregunta vacia, demasiado larga o "
        "historial con un rol invalido.",
        {
            "detail": [
                {
                    "type": "string_too_short",
                    "loc": ["body", "question"],
                    "msg": "String should have at least 1 character",
                }
            ]
        },
        model=None,
    ),
    RATE_LIMITED_STATUS: RATE_LIMITED_DOC,
    MODEL_UNAVAILABLE_STATUS: _error_doc(
        "El modelo real no respondio a tiempo o fallo.",
        {"detail": MODEL_UNAVAILABLE_DETAIL, "request_id": "3f2b9c1e-demo"},
        model=ErrorWithRequestId,
    ),
}
METRICS_RESPONSES = {
    UNAUTHORIZED_STATUS: UNAUTHORIZED_DOC,
    RATE_LIMITED_STATUS: RATE_LIMITED_DOC,
}


class AskResponse(BaseModel):
    """Respuesta de ``POST /ask``.

    ``model``, ``route``, ``cached_calls`` y ``cost_usd`` se omiten solo cuando
    se inyecta un modelo sin nombre (``create_app(llm=...)``): sin nombre no
    hay precio. ``cache`` (``hit`` o ``miss``) solo aparece con la cache de
    respuestas encendida. ``pii_detected`` (tipos sin repetir, en orden
    alfabetico) solo aparece si se enmascararon datos sensibles.
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
    cache: Literal["hit", "miss"] | None = None
    pii_detected: list[str] | None = None


class HealthResponse(BaseModel):
    """Respuesta de ``GET /health``."""

    status: str
    pid: int
    version: str


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
    :param response_cache: Cache de respuestas, o ``None`` si esta apagada
    :type response_cache: app.cache.ResponseCache or None
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
    response_cache: ResponseCache | None = None


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
        # ``/ask`` deja su costo en ``state``; si no llego al agente, cuesta 0.
        cost_usd = None
        if path == ASK_PATH:
            cost_usd = getattr(request.state, COST_STATE, 0.0)
        deps.logger.bind(request_id, client).request(
            method=request.method,
            path=path,
            status=response.status_code,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
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
    api_key_scheme = APIKeyHeader(
        name=API_KEY_HEADER, auto_error=False, description=API_KEY_DESCRIPTION
    )

    def require_client(
        request: Request, api_key: str | None = Security(api_key_scheme)
    ) -> str:
        """Devuelve el cliente dueno de la clave o corta la peticion.

        Cada 401 suma ``security.auth_failures`` y deja un ``audit``
        ``auth_failed`` (``client`` nulo); cada 429 suma
        ``security.rate_limited`` y deja un ``audit`` ``rate_limited``. La
        clave nunca se registra.

        :param request: Peticion entrante; guarda el cliente en ``state``
        :type request: fastapi.Request
        :param api_key: Valor de ``X-API-Key`` o ``None``
        :type api_key: str or None
        :return: Nombre del cliente
        :rtype: str
        :raises fastapi.HTTPException: 401 sin clave o con una invalida; 429
            con ``Retry-After`` si el cliente paso su limite
        """
        request_id = request.state.request_id
        client = deps.authenticator.authenticate(api_key)
        if client is None:
            deps.metrics.add_security_event(SECURITY_AUTH_FAILURES)
            deps.logger.bind(request_id).security_audit(AUDIT_AUTH_FAILED)
            raise HTTPException(
                status_code=UNAUTHORIZED_STATUS, detail=UNAUTHORIZED_DETAIL
            )
        request.state.client = client
        decision = deps.rate_limiter.check(client)
        if not decision.allowed:
            deps.metrics.add_security_event(SECURITY_RATE_LIMITED)
            deps.logger.bind(request_id, client).security_audit(AUDIT_RATE_LIMITED)
            raise HTTPException(
                status_code=RATE_LIMITED_STATUS,
                detail=RATE_LIMITED_DETAIL,
                headers={RETRY_AFTER_HEADER: str(decision.retry_after)},
            )
        return client

    return require_client


def _cache_key_for(deps: AppDependencies, question: str, model: str, history):
    """Calcula la clave de cache con la ventana de historial que vera el modelo.

    :param deps: Dependencias de la aplicacion
    :type deps: AppDependencies
    :param question: Pregunta que se mandaria al agente
    :type question: str
    :param model: Modelo elegido por el enrutador
    :type model: str
    :param history: Historial completo del cliente
    :type history: list[dict]
    :return: Clave de ``app.cache.cache_key``
    :rtype: str
    """
    window = CostOptions(history_window=deps.settings.history_window).window(
        history
    )
    return response_cache.cache_key(question, model, window)


def _cached_response(
    deps: AppDependencies, cached: CachedAnswer, reason: str, request_id: str
) -> AskResponse:
    """Arma la respuesta de un acierto de cache: sin tokens ni costo.

    Cuenta el acierto en ``/metrics`` y, si se reporta el costo, suma una
    respuesta de 0 USD para ``cost_usd_per_request``.

    :param deps: Dependencias de la aplicacion
    :type deps: AppDependencies
    :param cached: Respuesta guardada
    :type cached: app.cache.CachedAnswer
    :param reason: Motivo del enrutador para esta peticion
    :type reason: str
    :param request_id: Id de la peticion
    :type request_id: str
    :return: Respuesta con ``cache: "hit"``
    :rtype: AskResponse
    """
    deps.metrics.record_cache(hit=True)
    response = AskResponse(
        answer=cached.answer,
        steps=cached.steps,
        tools_used=list(cached.tools_used),
        input_tokens=0,
        output_tokens=0,
        request_id=request_id,
        cache=CACHE_HIT,
    )
    return _with_cost(
        deps,
        response,
        {"model": cached.model, "route": reason, "cached_calls": 0, "cost_usd": 0.0},
    )


def _with_cost(deps: AppDependencies, response: AskResponse, fields: dict):
    """Agrega los campos de costo y suma el costo en ``/metrics``.

    Si no se reporta el costo (``llm`` inyectado), devuelve la respuesta tal
    cual y no suma nada.

    :param deps: Dependencias de la aplicacion
    :type deps: AppDependencies
    :param response: Respuesta armada
    :type response: AskResponse
    :param fields: ``model``, ``route``, ``cached_calls`` y ``cost_usd``
    :type fields: dict
    :return: La respuesta, con los campos de costo si se reportan
    :rtype: AskResponse
    """
    if not deps.report_cost:
        return response
    deps.metrics.add_cost(fields["cost_usd"])
    return response.model_copy(update=fields)


def _lookup_cache(
    deps: AppDependencies, guarded: GuardedInput, chosen, request_id: str
) -> tuple:
    """Busca la pregunta ya enmascarada en la cache de respuestas.

    :param deps: Dependencias de la aplicacion
    :type deps: AppDependencies
    :param guarded: Pregunta e historial ya enmascarados
    :type guarded: app.guardrails.GuardedInput
    :param chosen: Decision del enrutador
    :type chosen: app.router.Route
    :param request_id: Id de la peticion
    :type request_id: str
    :return: Clave de cache (``None`` sin cache) y la respuesta del acierto
        (``None`` si no hubo)
    :rtype: tuple[str or None, AskResponse or None]
    """
    if deps.response_cache is None:
        return None, None
    key = _cache_key_for(deps, guarded.question, chosen.model, guarded.history)
    cached = deps.response_cache.get(key)
    if cached is None:
        return key, None
    response = _cached_response(deps, cached, chosen.reason, request_id)
    return key, _with_pii(response, guarded.pii_types)


def _agent_response(result, answer: str, request_id: str) -> AskResponse:
    """Arma la respuesta del agente con la salida ya validada.

    :param result: Resultado del agente
    :type result: app.agent.AgentResult
    :param answer: Respuesta validada por las guardas de salida
    :type answer: str
    :param request_id: Id de la peticion
    :type request_id: str
    :return: Respuesta sin campos de cache, PII ni costo
    :rtype: AskResponse
    """
    return AskResponse(
        answer=answer,
        steps=result.steps,
        tools_used=result.tools_used,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        request_id=request_id,
    )


def _remember(  # pylint: disable=too-many-arguments
    deps: AppDependencies,
    key: str | None,
    response: AskResponse,
    *,
    inputs: list,
    model: str,
    storable: bool,
) -> AskResponse:
    """Guarda la respuesta ya validada si es segura y cuenta el fallo.

    Sin cache (``key`` es ``None``) devuelve la respuesta tal cual. No se
    guarda si las guardas encontraron datos sensibles o bloquearon la salida
    (``storable`` en falso); ``app.cache.is_storable`` queda como defensa en
    profundidad.

    :param deps: Dependencias de la aplicacion
    :type deps: AppDependencies
    :param key: Clave de cache de la pregunta ya enmascarada o ``None``
    :type key: str or None
    :param response: Respuesta validada que se guardaria
    :type response: AskResponse
    :param inputs: Pregunta y mensajes del historial tal como llegaron
    :type inputs: list[str]
    :param model: Modelo que respondio
    :type model: str
    :param storable: Si las guardas permiten guardarla
    :type storable: bool
    :return: La respuesta, con ``cache: "miss"`` si la cache esta encendida
    :rtype: AskResponse
    """
    if key is None:
        return response
    deps.metrics.record_cache(hit=False)
    secrets = [api_key.key for api_key in deps.settings.api_keys]
    if storable and response_cache.is_storable(inputs, response.answer, secrets):
        answer = CachedAnswer(
            answer=response.answer,
            steps=response.steps,
            tools_used=tuple(response.tools_used),
            model=model,
        )
        deps.response_cache.put(key, answer)
    return response.model_copy(update={"cache": CACHE_MISS})


def _check_input(guard: RequestGuard, question: str, history: list) -> GuardedInput:
    """Aplica las guardas de entrada y convierte un rechazo en ``400``.

    :param guard: Guardas de la peticion
    :type guard: app.guardrails.RequestGuard
    :param question: Pregunta tal como llego
    :type question: str
    :param history: Mensajes con ``role`` y ``content``
    :type history: list[dict]
    :return: Pregunta e historial enmascarados
    :rtype: app.guardrails.GuardedInput
    :raises fastapi.HTTPException: 400 con inyeccion o, con
        ``PII_POLICY=block``, con datos sensibles
    """
    try:
        return guard.check_input(question, history)
    except InputRejected as error:
        raise HTTPException(
            status_code=INPUT_REJECTED_STATUS, detail=error.detail
        ) from error


def _run_agent(deps: AppDependencies, guarded: GuardedInput, chosen, log):
    """Crea el agente de esta peticion y lo corre con la entrada enmascarada.

    :param deps: Dependencias de la aplicacion
    :type deps: AppDependencies
    :param guarded: Pregunta e historial ya enmascarados
    :type guarded: app.guardrails.GuardedInput
    :param chosen: Decision del enrutador
    :type chosen: app.router.Route
    :param log: Emisor de eventos de la peticion
    :type log: app.telemetry.RequestLog
    :return: Resultado del agente
    :rtype: app.agent.AgentResult
    """
    settings = deps.settings
    agent = Agent(
        llm=deps.models[chosen.model],
        directory=deps.directory,
        max_steps=settings.agent_max_steps,
        telemetry=log,
        tracer=deps.tracer,
        clock=deps.clock,
        environment=settings.environment,
        model=chosen.model,
        route=chosen.reason,
        history_window=settings.history_window,
        prices=deps.prices,
    )
    result = agent.run(guarded.question, guarded.history)
    deps.metrics.add_tokens(
        input_tokens=result.input_tokens, output_tokens=result.output_tokens
    )
    return result


def _with_pii(response: AskResponse, *found: tuple) -> AskResponse:
    """Agrega ``pii_detected`` si alguna guarda encontro datos sensibles.

    :param response: Respuesta armada
    :type response: AskResponse
    :param found: Tipos encontrados en la entrada y en la respuesta
    :type found: tuple[str, ...]
    :return: La respuesta, con ``pii_detected`` solo si hubo
    :rtype: AskResponse
    """
    types = sorted({kind for kinds in found for kind in kinds})
    if not types:
        return response
    return response.model_copy(update={"pii_detected": types})


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

    @application.get(
        "/",
        response_class=HTMLResponse,
        tags=[TAG_OPERATIONS],
        summary="Pagina web",
        description="Formulario para preguntar; la clave vive en la pestana.",
    )
    def home() -> HTMLResponse:
        """Sirve la pagina web."""
        return HTMLResponse(page)

    @application.get(
        "/health",
        response_model=HealthResponse,
        tags=[TAG_OPERATIONS],
        summary="Salud del proceso",
        description=(
            "Dice que el proceso esta vivo, su `pid` (con varios workers indica "
            "cual respondio) y la version desplegada. No pide clave."
        ),
    )
    def health() -> HealthResponse:
        """Informa que el proceso esta vivo, su id y la version."""
        return HealthResponse(
            status="ok", pid=os.getpid(), version=settings.app_version
        )

    @application.get(
        METRICS_PATH,
        dependencies=[Depends(require_client)],
        tags=[TAG_OPERATIONS],
        summary="Metricas de este proceso",
        description=(
            "Peticiones, errores por familia, latencia p50/p95, tokens, costo, "
            "eventos de seguridad, cache de respuestas y SLO de este proceso "
            "(`pid`). Exige `X-API-Key`."
        ),
        responses=METRICS_RESPONSES,
    )
    def metrics() -> dict:
        """Devuelve las metricas de este proceso (exige clave)."""
        return deps.metrics.snapshot(slo_p95_ms=settings.slo_p95_ms)

    @application.post(
        ASK_PATH,
        response_model=AskResponse,
        response_model_exclude_none=True,
        tags=[TAG_CHAT],
        summary="Preguntar al asistente de RH",
        description=(
            "Responde una pregunta sobre empleados con el historial opcional "
            "de la conversacion. Dice que modelo uso, por que y cuanto costo. "
            "Exige `X-API-Key` y respeta el limite por cliente."
        ),
        responses=ASK_RESPONSES,
    )
    def ask(
        payload: ask_request,
        request: Request,
        client: str = Depends(require_client),
    ) -> AskResponse:
        """Enruta la pregunta y la responde; el agente se crea por peticion.

        Es una funcion normal: FastAPI la corre en su pool de hilos y no
        bloquea el bucle de eventos. Tras la clave, el limite y el esquema,
        rechaza la inyeccion y enmascara los datos sensibles antes del
        enrutador, la cache, el agente, el log y la traza; la salida se valida
        antes de guardarla y devolverla. Con la cache de respuestas encendida,
        una pregunta repetida se responde sin crear el agente.
        """
        request_id = request.state.request_id
        log = deps.logger.bind(request_id, client)
        guard = RequestGuard(log, deps.metrics, settings)
        history = [message.model_dump() for message in payload.history]
        guarded = _check_input(guard, payload.question, history)
        chosen = route(guarded.question, settings)
        key, hit = _lookup_cache(deps, guarded, chosen, request_id)
        if hit is not None:
            setattr(request.state, COST_STATE, 0.0)
            return hit
        result = _run_agent(deps, guarded, chosen, log)
        setattr(request.state, COST_STATE, result.cost_usd)
        output = guard.check_output(result.answer)
        response = _remember(
            deps,
            key,
            _agent_response(result, output.answer, request_id),
            inputs=[payload.question, *(item["content"] for item in history)],
            model=result.model,
            storable=not (guarded.pii_types or output.pii_types or output.blocked),
        )
        response = _with_pii(response, guarded.pii_types, output.pii_types)
        return _with_cost(
            deps,
            response,
            {
                "model": result.model,
                "route": chosen.reason,
                "cached_calls": result.cached_calls,
                "cost_usd": result.cost_usd,
            },
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


def _build_response_cache(settings: Settings) -> ResponseCache | None:
    """Crea la cache de respuestas si la configuracion la enciende.

    Lleva su propio reloj del sistema: asi no altera las lecturas del reloj
    de latencias.

    :param settings: Configuracion validada
    :type settings: app.config.Settings
    :return: La cache, o ``None`` si ``RESPONSE_CACHE_TTL_SECONDS`` es 0
    :rtype: app.cache.ResponseCache or None
    """
    if settings.response_cache_ttl_seconds <= 0:
        return None
    return ResponseCache(
        max_entries=settings.response_cache_size,
        ttl_seconds=settings.response_cache_ttl_seconds,
        clock=SystemClock(),
    )


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
    response_cache: ResponseCache | None = None,
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
    :param response_cache: Cache de respuestas con su reloj ya inyectado; por
        omision, si ``RESPONSE_CACHE_TTL_SECONDS`` es mayor que 0, una de
        ``RESPONSE_CACHE_SIZE`` entradas con el reloj del sistema
    :type response_cache: app.cache.ResponseCache or None
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
    models, report_cost = _build_models(settings, directory, llm, http_client)
    deps = AppDependencies(
        settings=settings,
        models=models,
        prices=PriceTable.load(settings.prices_path),
        report_cost=report_cost,
        directory=directory,
        clock=clock,
        logger=JsonLogger(
            log_stream if log_stream is not None else sys.stdout,
            clock,
            settings.service_name,
        ),
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
        response_cache=(
            response_cache
            if response_cache is not None
            else _build_response_cache(settings)
        ),
    )
    application = FastAPI(
        title=API_TITLE,
        version=settings.app_version,
        description=API_DESCRIPTION,
        openapi_tags=OPENAPI_TAGS,
    )
    _add_observability_middleware(application, deps)
    _add_error_handlers(application, deps)
    _add_routes(
        application, deps, (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    )
    return application


app = create_app()
