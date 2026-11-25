"""API REST del HR Assistant (FastAPI) con el servidor MCP montado en ``/mcp``.

- Sin estado: cada copia del proceso atiende cualquier petición; escalar es
  correr más copias (``WEB_CONCURRENCY`` o más instancias en Render).
- Asíncrona de punta a punta: las llamadas al modelo no bloquean el proceso.
- Seguridad en capas: clave por cliente con permisos, límite de peticiones,
  validación de entradas y salidas, PII enmascarada, auditoría y encabezados
  de seguridad.
"""

from __future__ import annotations

import secrets
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field

from app.clock import Clock, SystemClock
from app.config import ConfigError, Settings, load_settings
from app.domain.directory import NotFoundError
from app.llm.base import ChatModel, ModelUnavailable
from app.mcp_server.server import build_mcp_server
from app.observability.logs import JsonLogger, channel_var, client_var, request_id_var
from app.security.access import Authenticator, RateLimiter, extract_key
from app.security.guards import GuardRejection
from app.service import HrService, build_services

STATIC = Path(__file__).resolve().parent / "static"
PUBLIC_PATHS = {
    "/",
    "/health",
    "/ready",
    "/dashboard",
    "/docs",
    "/openapi.json",
    "/favicon.ico",
}
SCOPE_BY_PREFIX = (
    ("/metrics", "metrics"),
    ("/mcp", "mcp"),
    ("/ask", "ask"),
    ("/tools", "ask"),
)
MAX_HISTORY = 50


class HistoryMessage(BaseModel):
    """Un mensaje previo de la conversación (lo guarda el cliente)."""

    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class AskRequest(BaseModel):
    """Cuerpo de ``POST /ask``."""

    question: str = Field(
        description="Pregunta en español", examples=["¿Quién es EMP-0004?"]
    )
    history: list[HistoryMessage] = Field(default_factory=list, max_length=MAX_HISTORY)


class VacationRequest(BaseModel):
    """Cuerpo de ``POST /tools/vacation-balance``."""

    employee_id: str = Field(pattern=r"^EMP-\d{4}$", examples=["EMP-0004"])
    context: str = Field(default="", max_length=500)


class SummaryRequest(BaseModel):
    """Cuerpo de ``POST /tools/department-summary``."""

    department: str = Field(min_length=2, max_length=60, examples=["Tecnología"])


def _required_scope(path: str) -> str | None:
    if path in PUBLIC_PATHS or path.startswith("/static"):
        return None
    for prefix, scope in SCOPE_BY_PREFIX:
        if path == prefix or path.startswith(prefix + "/"):
            return scope
    return None


def _page(name: str, nonce: str) -> HTMLResponse:
    html = (STATIC / name).read_text(encoding="utf-8").replace("{{nonce}}", nonce)
    csp = (
        "default-src 'self'; "
        f"script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
        "base-uri 'none'; form-action 'self'"
    )
    return HTMLResponse(html, headers={"Content-Security-Policy": csp})


def _mcp_security(env_host: str) -> TransportSecuritySettings:
    hosts = ["localhost:*", "127.0.0.1:*", "testserver"]
    origins = ["http://localhost:*", "http://127.0.0.1:*"]
    if env_host:
        hosts += [env_host, f"{env_host}:*"]
        origins.append(f"https://{env_host}")
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=origins,
    )


def create_app(  # pylint: disable=too-many-locals,too-many-statements
    settings: Settings | None = None,
    clock: Clock | None = None,
    model: ChatModel | None = None,
    logger: JsonLogger | None = None,
    public_host: str = "",
) -> FastAPI:
    """Arma la aplicación con sus dependencias (las pruebas inyectan las suyas).

    :param settings: Configuración; por omisión se lee del entorno
    :type settings: Settings | None
    :param clock: Reloj; por omisión el del sistema
    :type clock: Clock | None
    :param model: Modelo; por omisión según ``MODEL_PROVIDER``
    :type model: ChatModel | None
    :param logger: Log; por omisión JSON a stdout
    :type logger: JsonLogger | None
    :param public_host: Nombre público del servicio (protección DNS rebinding de MCP)
    :type public_host: str
    :return: Aplicación FastAPI
    :rtype: FastAPI
    """
    settings = settings or load_settings()
    clock = clock or SystemClock()
    logger = logger or JsonLogger(
        settings.service_name, clock, audit_path=settings.audit_log_path
    )
    service = HrService(build_services(settings, clock, logger, model=model))
    metrics = service.s.metrics
    auth = Authenticator(settings.api_clients)
    limiter = RateLimiter(settings.rate_limit_per_minute, clock)
    mcp_server = build_mcp_server(service, default_client="mcp-http")
    mcp_app = mcp_server.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=_mcp_security(public_host),
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        logger.event(
            "startup",
            environment=settings.environment,
            provider=settings.model_provider,
            tracing=service.s.tracer.enabled,
            clients=len(settings.api_clients),
        )
        async with mcp_server.session_manager.run():
            yield
        closer = getattr(service.s.model, "aclose", None)
        if closer is not None:
            await closer()
        service.s.tracer.flush()

    app = FastAPI(
        title="HR Assistant",
        version="1.0.0",
        description=(
            "Asistente de Recursos Humanos multiagente (LangGraph). Las rutas "
            "protegidas "
            "piden el encabezado `X-API-Key`. El servidor MCP está en `/mcp` "
            "(Streamable HTTP)."
        ),
        lifespan=lifespan,
        redoc_url=None,
    )
    app.state.service = service

    @app.middleware("http")
    async def gatekeeper(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request_id = request_id[:128]
        tokens = [
            request_id_var.set(request_id),
            client_var.set("-"),
            channel_var.set("mcp" if request.url.path.startswith("/mcp") else "api"),
        ]
        started = clock.monotonic()
        try:
            response = await _guarded(request, call_next)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.event("error", error_type=type(exc).__name__, path=request.url.path)
            response = JSONResponse(
                {"detail": "internal error", "request_id": request_id}, status_code=500
            )
        latency = round((clock.monotonic() - started) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers.setdefault("Cache-Control", "no-store")
        metrics.record_request(response.status_code, latency)
        logger.event(
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            latency_ms=latency,
        )
        for token in reversed(tokens):
            token.var.reset(token)
        return response

    async def _guarded(request: Request, call_next):
        scope = _required_scope(request.url.path)
        if scope is None:
            return await call_next(request)
        client = auth.identify(extract_key(request.headers))
        if client is None:
            logger.audit("auth_failed", path=request.url.path)
            metrics.increment("auth_failed")
            return JSONResponse(
                {"detail": "invalid or missing API key"}, status_code=401
            )
        client_var.set(client.name)
        if scope not in client.scopes:
            logger.audit("forbidden", path=request.url.path, scope=scope)
            metrics.increment("forbidden")
            return JSONResponse(
                {"detail": "client not allowed for this resource"}, status_code=403
            )
        wait = limiter.check(client.name)
        if wait:
            logger.audit("rate_limited", path=request.url.path, retry_after=wait)
            metrics.increment("rate_limited")
            return JSONResponse(
                {"detail": "rate limit exceeded"},
                status_code=429,
                headers={"Retry-After": str(wait)},
            )
        return await call_next(request)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, exc: RequestValidationError):
        # No se devuelve el valor recibido: podría traer datos personales
        fields = sorted(
            {".".join(map(str, e["loc"][1:])) or "body" for e in exc.errors()}
        )
        return JSONResponse(
            {
                "detail": "invalid request",
                "fields": fields,
                "request_id": request_id_var.get(),
            },
            status_code=422,
        )

    @app.exception_handler(GuardRejection)
    async def rejected(_: Request, exc: GuardRejection):
        return JSONResponse(
            {
                "detail": "question rejected by security policy",
                "reason": exc.reason,
                "request_id": request_id_var.get(),
            },
            status_code=400,
        )

    @app.exception_handler(ModelUnavailable)
    async def model_down(_: Request, exc: ModelUnavailable):
        logger.event("error", error_type="ModelUnavailable", cause=str(exc))
        return JSONResponse(
            {"detail": "model unavailable", "request_id": request_id_var.get()},
            status_code=502,
        )

    @app.exception_handler(NotFoundError)
    async def not_found(_: Request, exc: NotFoundError):
        return JSONResponse(
            {"detail": str(exc), "request_id": request_id_var.get()}, status_code=404
        )

    @app.get("/", include_in_schema=False)
    async def home() -> HTMLResponse:
        return _page("index.html", secrets.token_urlsafe(16))

    @app.get("/dashboard", include_in_schema=False)
    async def dashboard() -> HTMLResponse:
        return _page("dashboard.html", secrets.token_urlsafe(16))

    @app.get("/health", tags=["operación"])
    async def health() -> dict:
        """Prueba de vida: el proceso responde."""
        import os  # pylint: disable=import-outside-toplevel

        return {"status": "ok", "pid": os.getpid()}

    @app.get("/ready", tags=["operación"])
    async def ready() -> dict:
        """Prueba de disponibilidad: datos cargados y configuración del modelo."""
        return {
            "status": "ready",
            "employees_loaded": bool(service.s.directory.departments()),
            "model_provider": settings.model_provider,
            "tracing": service.s.tracer.enabled,
        }

    @app.post("/ask", tags=["agentes"])
    async def ask(body: AskRequest) -> dict:
        """Pregunta libre: el supervisor responde o delega en un especialista."""
        question = body.question
        if not question.strip() or len(question) > settings.max_question_chars:
            raise RequestValidationError(
                [
                    {
                        "loc": ("body", "question"),
                        "msg": "invalid length",
                        "type": "value",
                    }
                ]
            )
        history = [m.model_dump() for m in body.history]
        result = await service.ask(question, history)
        return {**result, "request_id": request_id_var.get()}

    @app.post("/tools/vacation-balance", tags=["agentes"])
    async def vacation_balance(body: VacationRequest) -> dict:
        """Saldo de vacaciones con el agente ReAct (equivale a la herramienta MCP)."""
        result = await service.vacation(body.employee_id, body.context)
        return {**result, "request_id": request_id_var.get()}

    @app.post("/tools/department-summary", tags=["agentes"])
    async def department_summary(body: SummaryRequest) -> dict:
        """Resumen de un área con el agente de reflexión (como la herramienta MCP)."""
        result = await service.summary(body.department)
        return {**result, "request_id": request_id_var.get()}

    @app.get("/metrics", tags=["operación"])
    async def get_metrics() -> dict:
        """Métricas de este proceso: latencia, errores, tokens, costo y negocio."""
        return metrics.snapshot()

    @app.get(
        "/metrics/prometheus", tags=["operación"], response_class=PlainTextResponse
    )
    async def get_prometheus() -> str:
        """Las mismas métricas en formato de texto de Prometheus."""
        return metrics.prometheus(settings.service_name)

    app.mount("/", mcp_app)
    return app


def _build_default() -> FastAPI:
    import os  # pylint: disable=import-outside-toplevel

    try:
        return create_app(public_host=os.environ.get("RENDER_EXTERNAL_HOSTNAME", ""))
    except ConfigError as exc:
        # El mensaje ya viene sin secretos; se sale con código distinto de 0
        print(f"Configuración inválida: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


app = _build_default()
