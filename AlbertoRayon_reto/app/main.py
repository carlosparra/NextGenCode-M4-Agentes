"""API del HR Assistant: FastAPI sin estado, con el servidor MCP montado en /mcp."""

import os
import re
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Request, Security
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

from app.access import Authenticator, RateLimiter
from app.clock import SystemClock
from app.config import Settings, load_settings
from app.guards import GuardBlocked
from app.llm import ModelUnavailable
from app.logs import channel_var, client_var, request_id_var
from app.mcp_server import build_mcp, http_app
from app.service import HRService

STATIC = Path(__file__).resolve().parent / "static"
REQUEST_ID = re.compile(r"^[\w.:-]{1,64}$")
SCOPE_BY_PATH = {"/ask": "ask", "/metrics": "metrics", "/metrics/prometheus": "metrics"}
RATE_LIMITED = {"ask", "mcp"}
PAGES = {"/": "index.html", "/dashboard": "dashboard.html"}
API_KEY_HEADER = APIKeyHeader(
    name="X-API-Key", auto_error=False, description="Clave del cliente"
)
DESCRIPTION = (
    "Asistente de Recursos Humanos multiagente: un supervisor reparte cada pregunta "
    "a un agente LangGraph (directorio, vacaciones o resúmenes). Las mismas "
    "capacidades están disponibles como servidor MCP en `/mcp`."
)


class HistoryMessage(BaseModel):
    """Un mensaje anterior de la conversación."""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class AskRequest(BaseModel):
    """Pregunta para el HR Assistant."""

    question: str = Field(min_length=1, description="Pregunta en español")
    history: list[HistoryMessage] = Field(
        default_factory=list, description="Conversación anterior; la manda el cliente"
    )


class AskResponse(BaseModel):
    """Respuesta del HR Assistant, con lo que costó producirla."""

    answer: str
    steps: int
    tools_used: list[str]
    input_tokens: int
    output_tokens: int
    request_id: str
    model: str
    route: str
    cached_calls: int
    cost_usd: float
    agent: str
    reasoning: list[str]
    pii_masked: list[str]
    cache: str


def _scope_for(path: str) -> str | None:
    if path == "/mcp" or path.startswith("/mcp/"):
        return "mcp"
    return SCOPE_BY_PATH.get(path)


def _error(status: int, detail, request_id: str, **headers) -> JSONResponse:
    return JSONResponse(
        {"detail": detail, "request_id": request_id}, status_code=status,
        headers=headers,
    )


def create_app(  # pylint: disable=too-many-locals,too-many-statements
    settings: Settings | None = None, model=None, clock=None
) -> FastAPI:
    """Crea la aplicación con sus dependencias.

    :param settings: Configuración; por omisión se lee del entorno
    :type settings: Settings | None
    :param model: Modelo a usar; por omisión, el que diga la configuración
    :param clock: Reloj; por omisión, el del sistema
    :return: Aplicación lista para uvicorn
    :rtype: fastapi.FastAPI
    """
    settings = settings or load_settings()
    clock = clock or SystemClock()
    service = HRService(settings, model=model, clock=clock)
    auth = Authenticator(settings)
    limiter = RateLimiter(settings.rate_limit_per_minute, clock)
    mcp = build_mcp(service)
    mcp_app = http_app(mcp, settings.mcp_allowed_hosts)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        async with mcp.session_manager.run():
            yield

    app = FastAPI(
        title="HR Assistant", version="1.0.0", description=DESCRIPTION,
        lifespan=lifespan,
    )
    app.state.service = service

    def gate(request: Request, request_id: str) -> JSONResponse | None:
        scope = _scope_for(request.url.path)
        if scope is None:
            return None
        client = auth.identify(request.headers.get("X-API-Key"))
        if client is None:
            service.metrics.count("auth_failed")
            service.logger.audit("auth_failed", path=request.url.path)
            return _error(401, "invalid or missing API key", request_id)
        client_var.set(client)
        if not auth.allowed(client, scope):
            service.metrics.count("scope_denied")
            service.logger.audit("scope_denied", path=request.url.path, scope=scope)
            return _error(403, "insufficient scope", request_id)
        if scope in RATE_LIMITED:
            wait = limiter.retry_after(client)
            if wait:
                service.metrics.count("rate_limited")
                service.logger.audit("rate_limited", retry_after=wait)
                return _error(
                    429, "rate limit exceeded", request_id, **{"Retry-After": str(wait)}
                )
        return None

    @app.middleware("http")
    async def observe_and_protect(request: Request, call_next):
        given = request.headers.get("X-Request-ID", "")
        request_id = given if REQUEST_ID.match(given) else str(uuid.uuid4())
        request_id_var.set(request_id)
        client_var.set("-")
        path = request.url.path
        channel_var.set("mcp-http" if _scope_for(path) == "mcp" else "http")
        started = time.perf_counter()
        response = gate(request, request_id)
        if response is None:
            try:
                response = await call_next(request)
            except Exception as error:  # pylint: disable=broad-exception-caught
                service.logger.event("error", error_type=type(error).__name__)
                response = _error(500, "internal error", request_id)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if path not in PAGES and not path.startswith("/docs"):
            response.headers["Cache-Control"] = "no-store"
        latency = (time.perf_counter() - started) * 1000
        service.metrics.record_request(response.status_code, latency)
        service.logger.event(
            "request", method=request.method, path=path,
            status=response.status_code, latency_ms=round(latency, 2),
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, error: RequestValidationError):
        # No se devuelve la entrada: solo qué campo falla y por qué
        problems = [
            {"field": ".".join(map(str, item["loc"])), "error": item["type"]}
            for item in error.errors()
        ]
        return _error(422, problems, request_id_var.get())

    @app.exception_handler(GuardBlocked)
    async def blocked(_request: Request, error: GuardBlocked):
        return _error(400, f"request blocked: {error.reason}", request_id_var.get())

    @app.exception_handler(ModelUnavailable)
    async def model_down(_request: Request, _error_: ModelUnavailable):
        service.logger.event("error", error_type="ModelUnavailable")
        return _error(502, "model unavailable", request_id_var.get())

    def page(name: str) -> HTMLResponse:
        nonce = secrets.token_urlsafe(16)
        html = (STATIC / name).read_text(encoding="utf-8").replace("__NONCE__", nonce)
        policy = (
            f"default-src 'none'; script-src 'nonce-{nonce}'; "
            f"style-src 'nonce-{nonce}'; connect-src 'self'; base-uri 'none'; "
            "form-action 'none'; frame-ancestors 'none'"
        )
        return HTMLResponse(html, headers={"Content-Security-Policy": policy})

    @app.get("/", include_in_schema=False)
    def home() -> HTMLResponse:
        return page("index.html")

    @app.get("/dashboard", include_in_schema=False)
    def dashboard() -> HTMLResponse:
        return page("dashboard.html")

    @app.get("/health", tags=["operación"], summary="Health check")
    def health() -> dict:
        return {
            "status": "ok", "pid": os.getpid(), "environment": settings.environment,
            "model_provider": settings.model_provider,
            "tracing": service.tracing_enabled,
        }

    @app.post(
        "/ask", response_model=AskResponse, tags=["agentes"],
        summary="Pregunta al sistema multiagente",
        responses={400: {"description": "Bloqueada por la guarda de entrada"},
                   401: {"description": "Clave inválida"},
                   403: {"description": "La clave no tiene el permiso ask"},
                   429: {"description": "Límite de peticiones"},
                   502: {"description": "El modelo no responde"}},
    )
    def ask(body: AskRequest, _key: str | None = Security(API_KEY_HEADER)) -> dict:
        too_long = len(body.question) > settings.max_question_chars
        too_many = len(body.history) > settings.max_history_messages
        if too_long or too_many or not body.question.strip():
            field = "body.history" if too_many else "body.question"
            return _error(
                422, [{"field": field, "error": "out_of_range"}], request_id_var.get()
            )
        return service.ask(body.question, [m.model_dump() for m in body.history])

    @app.get("/metrics", tags=["operación"], summary="Métricas de este proceso")
    def metrics(_key: str | None = Security(API_KEY_HEADER)) -> dict:
        return service.metrics.snapshot()

    @app.get(
        "/metrics/prometheus", tags=["operación"], response_class=PlainTextResponse,
        summary="Métricas en formato Prometheus",
    )
    def prometheus(_key: str | None = Security(API_KEY_HEADER)) -> str:
        return service.metrics.prometheus(settings.service_name)

    app.mount("/", mcp_app)
    return app


app = create_app()
