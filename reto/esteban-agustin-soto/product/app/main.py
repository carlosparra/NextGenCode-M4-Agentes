"""Aplicación FastAPI sin estado del HR Assistant, con observabilidad."""

import os
import re
import uuid
from functools import partial
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse

from app import api_docs
from app.agent import Agent
from app.api_docs import AskRequest
from app.compliance import check_production
from app.config import load_settings
from app.directory import EmployeeDirectory
from app.llm import ModelUnavailable, build_models
from app.observability import (
    Clock, JsonLogger, MetricsCollector, client_var, request_id_var,
)
from app.pii import (
    CURP_KIND, EMAIL_KIND, empty_counts, mask_counted, mask_deep,
)
from app.pricing import PriceTable
from app.router import choose_model
from app.security import RateLimiter, authenticate
from app.tracing import traced

INDEX_PATH = Path(__file__).resolve().parent / "static" / "index.html"
REQUEST_ID_HEADER = "X-Request-ID"
API_KEY_HEADER = api_docs.API_KEY_HEADER
_VALID_REQUEST_ID = re.compile(r"[\x20-\x7e]{1,128}")


def resolve_request_id(received):
    """Acepta el id recibido solo si es corto e imprimible.

    :param received: Valor del encabezado ``X-Request-ID`` o ``None``
    :type received: str or None
    :return: El valor recibido o un UUID nuevo
    :rtype: str
    """
    if received and _VALID_REQUEST_ID.fullmatch(received):
        return received
    return str(uuid.uuid4())


def _install_middleware(api, clock, logger, metrics):
    """Instala el middleware que fija el id, mide y registra cada petición.

    :param api: Aplicación FastAPI
    :type api: fastapi.FastAPI
    :param clock: Reloj inyectado
    :param logger: Logger inyectado
    :param metrics: Colector de métricas
    :type metrics: app.observability.MetricsCollector
    """

    @api.middleware("http")
    async def observe(request: Request, call_next):
        request_id = resolve_request_id(request.headers.get(REQUEST_ID_HEADER))
        request_id_var.set(request_id)
        client_var.set(None)
        started = clock.now()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
        except Exception as error:  # pylint: disable=broad-exception-caught
            client_var.set(getattr(request.state, "client", None))
            logger.log("error", error_type=type(error).__name__)
            response = JSONResponse(
                status_code=500,
                content={"detail": "internal error", "request_id": request_id},
            )
        finally:
            latency_ms = (clock.now() - started).total_seconds() * 1000
            client_var.set(getattr(request.state, "client", None))
            logger.log(
                "request",
                method=request.method,
                path=request.url.path,
                status=status,
                latency_ms=round(latency_ms, 3),
            )
            metrics.record(latency_ms, status)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


def _make_require_client(settings, limiter):
    """Crea la dependencia que exige clave y aplica el límite.

    :param settings: Configuración con las claves por cliente
    :type settings: app.config.Settings
    :param limiter: Límite de peticiones por cliente
    :type limiter: app.security.RateLimiter
    :return: Dependencia de FastAPI que devuelve el nombre del cliente
    """

    async def require_client(request: Request):
        """Autentica con ``X-API-Key`` y cuenta la petición del cliente.

        :param request: Petición entrante
        :type request: fastapi.Request
        :return: Nombre del cliente autenticado
        :rtype: str
        :raises HTTPException: 401 si la clave falta o es inválida; 429 si
            el cliente superó su límite
        """
        client = authenticate(settings.api_keys, request.headers.get(API_KEY_HEADER))
        if client is None:
            raise HTTPException(status_code=401, detail="invalid or missing API key")
        request.state.client = client
        client_var.set(client)
        wait = limiter.check(client)
        if wait is not None:
            raise HTTPException(
                status_code=429, detail="rate limit exceeded",
                headers={"Retry-After": str(wait)},
            )
        return client

    return require_client


def _request_cost(prices, model_name, calls):
    """Suma el costo de cada llamada con el precio del modelo (única fórmula).

    :param prices: Tabla de precios
    :type prices: app.pricing.PriceTable
    :param model_name: Nombre del modelo usado
    :type model_name: str
    :param calls: Llamadas al modelo (``Completion``)
    :type calls: list
    :return: Costo en USD
    :rtype: float
    :raises ValueError: Si ``PriceTable.cost`` no encuentra precio para el
        modelo (es un error, no se asume costo 0)
    """
    return sum(
        prices.cost(model_name, call.input_tokens, call.output_tokens, call.cached)
        for call in calls
    )


def _audit_masked(logger, where, counts):
    """Emite el evento ``audit`` de enmascarado, solo con conteos.

    :param logger: Logger inyectado
    :param where: ``question``, ``history`` o ``answer``
    :type where: str
    :param counts: Conteos ``{"curp": n, "email": n}``
    :type counts: dict
    """
    if counts[CURP_KIND] or counts[EMAIL_KIND]:
        logger.log(
            "audit", action="pii_masked", where=where,
            curp=counts[CURP_KIND], email=counts[EMAIL_KIND],
        )


def _mask_history(history):
    """Enmascara el contenido de cada mensaje del historial.

    :param history: Mensajes previos como diccionarios
    :type history: list
    :return: Los mensajes enmascarados y los conteos sumados
    :rtype: tuple
    """
    total = empty_counts()
    masked = []
    for message in history:
        content, found = mask_counted(message["content"])
        masked.append({**message, "content": content})
        for kind, number in found.items():
            total[kind] += number
    return masked, total


def _mask_input(logger, question, history):
    """Enmascara la pregunta y el historial antes de llegar al agente.

    :param logger: Logger inyectado
    :param question: Pregunta ya recortada
    :type question: str
    :param history: Mensajes previos como diccionarios
    :type history: list
    :return: La pregunta y el historial enmascarados
    :rtype: tuple
    """
    question, counts = mask_counted(question)
    _audit_masked(logger, "question", counts)
    masked, total = _mask_history(history)
    _audit_masked(logger, "history", total)
    return question, masked


def _mask_answer(logger, answer):
    """Enmascara la respuesta antes de devolverla.

    :param logger: Logger inyectado
    :param answer: Respuesta del agente
    :type answer: str
    :return: La respuesta enmascarada
    :rtype: str
    """
    answer, counts = mask_counted(answer)
    _audit_masked(logger, "answer", counts)
    return answer


def _install_validation_masking(api):
    """Enmascara CURP y correo en el cuerpo de los 422 de validación.

    :param api: Aplicación FastAPI
    :type api: fastapi.FastAPI
    """

    @api.exception_handler(RequestValidationError)
    async def masked_validation(_request: Request, exc: RequestValidationError):
        """Devuelve el 422 de FastAPI con los datos personales enmascarados.

        :param _request: Petición entrante
        :type _request: fastapi.Request
        :param exc: Error de validación
        :type exc: fastapi.exceptions.RequestValidationError
        :return: Respuesta 422 con el mismo detalle, enmascarado
        :rtype: fastapi.responses.JSONResponse
        """
        detail = mask_deep(jsonable_encoder(exc.errors()))
        return JSONResponse(status_code=422, content={"detail": detail})


# pylint: disable=too-many-arguments,too-many-locals
def create_app(settings=None, *, model=None, directory=None, clock=None,
               logger=None, models=None, prices=None, limiter=None):
    """Construye la aplicación con sus dependencias.

    :param settings: Configuración; por omisión se lee del entorno
    :type settings: app.config.Settings or None
    :param model: Un único modelo para ambos roles (compatibilidad)
    :type model: object or None
    :param directory: Directorio de empleados; por omisión el de la config
    :type directory: app.directory.EmployeeDirectory or None
    :param clock: Reloj con ``now()``; por omisión el del sistema
    :type clock: object or None
    :param logger: Logger con ``log()``; por omisión JSON en la salida estándar
    :type logger: object or None
    :param models: Diccionario ``nombre -> modelo``; por omisión según la config
    :type models: dict or None
    :param prices: Tabla de precios; por omisión la de ``PRICES_PATH``
    :type prices: app.pricing.PriceTable or None
    :param limiter: Límite de peticiones; por omisión uno con el reloj inyectado
    :type limiter: app.security.RateLimiter or None
    :return: La aplicación FastAPI
    :rtype: fastapi.FastAPI
    :raises ValueError: Si es producción y la configuración viola una regla
    """
    settings = settings or load_settings(os.environ)
    violations = check_production(settings)
    if violations:
        raise ValueError("Unsafe production setup: " + "; ".join(violations))
    clock = clock or Clock()
    limiter = limiter or RateLimiter(settings.rate_limit_per_minute, clock)
    require_client = _make_require_client(settings, limiter)
    logger = logger or JsonLogger(
        settings.service_name, clock, masking=settings.pii_masking
    )
    directory = directory or EmployeeDirectory(settings.employees_path)
    if models is None and model is not None:
        models = {settings.model_small: model, settings.model_large: model}
    models = models or build_models(settings, directory.departments())
    prices = prices or PriceTable(settings.prices_path)
    metrics = MetricsCollector(settings.slo_p95_ms)
    api_key = os.environ.get("LANGSMITH_API_KEY")
    if settings.langsmith_tracing and not api_key:
        logger.log("tracing_disabled", reason="missing api key")
    trace = partial(
        traced,
        enabled=settings.langsmith_tracing,
        api_key=api_key,
        hide_inputs=settings.hide_inputs,
        hide_outputs=settings.hide_outputs,
    )
    api = FastAPI(
        title=api_docs.API_TITLE, summary=api_docs.API_SUMMARY,
        description=api_docs.API_DESCRIPTION, version=api_docs.API_VERSION,
        openapi_tags=api_docs.OPENAPI_TAGS,
    )
    _install_middleware(api, clock, logger, metrics)
    if settings.pii_masking:
        _install_validation_masking(api)
    secured = [Depends(require_client), Depends(api_docs.api_key_scheme)]

    @api.get(
        "/", summary="Página web del asistente", tags=[api_docs.TAG_APP],
        description="Sirve la página HTML para preguntar al asistente. "
        "No pide clave.",
    )
    def index():
        """Sirve la página web.

        :return: Archivo HTML de la página
        :rtype: fastapi.responses.FileResponse
        """
        return FileResponse(INDEX_PATH, media_type="text/html")

    @api.get(
        "/health", summary="Estado del proceso", tags=[api_docs.TAG_STATUS],
        description="Informa que el proceso está vivo y su pid. No pide clave.",
    )
    def health():
        """Informa que el proceso está vivo.

        :return: Estado y pid del proceso
        :rtype: dict
        """
        return {"status": "ok", "pid": os.getpid()}

    @api.get(
        "/metrics", dependencies=secured, summary="Métricas del proceso",
        tags=[api_docs.TAG_OPS], responses=api_docs.METRICS_RESPONSES,
        description="Entrega pid, peticiones, tasa de error, latencias, "
        "tokens, costo y estado del SLO de este proceso. Pide clave.",
    )
    def get_metrics():
        """Entrega las métricas de este proceso.

        :return: Pid y la foto actual de las métricas
        :rtype: dict
        """
        return {"pid": os.getpid(), **metrics.snapshot()}

    @api.post(
        "/ask", dependencies=secured, summary="Preguntar al asistente",
        tags=[api_docs.TAG_ASSISTANT], responses=api_docs.ASK_RESPONSES,
        description="Responde una pregunta sobre empleados con un agente de "
        "herramientas de solo lectura. No guarda nada entre peticiones; "
        "el historial viaja en el cuerpo. Pide clave.",
    )
    def ask(body: AskRequest):
        """Responde una pregunta; no guarda nada entre peticiones.

        :param body: Pregunta e historial opcional
        :type body: AskRequest
        :return: Respuesta con modelo, costo, tokens y ``request_id``; un 502
            si el modelo no está disponible
        :rtype: dict or fastapi.responses.JSONResponse
        :raises HTTPException: 422 si la pregunta está vacía o es muy larga
        """
        question = body.question.strip()
        if not question or len(body.question) > settings.max_question_chars:
            raise HTTPException(status_code=422, detail="Invalid question length")
        history = [m.model_dump() for m in body.history or []]
        if settings.pii_masking:
            question, history = _mask_input(logger, question, history)
        model_name, route = choose_model(question, settings)
        agent = Agent(
            model=models[model_name], directory=directory,
            max_steps=settings.agent_max_steps, logger=logger, trace=trace,
            history_window=settings.history_window, model_name=model_name,
            route=route,
            cost_fn=partial(_request_cost, prices, model_name),
        )
        try:
            result = agent.run(question, history)
        except ModelUnavailable as error:
            logger.log(
                "error", error_type=type(error).__name__,
                cause=error.cause, status_code=error.status_code,
            )
            return JSONResponse(
                status_code=502,
                content={"detail": "model unavailable",
                         "request_id": request_id_var.get()},
            )
        cost = result.cost_usd
        metrics.add_tokens(result.input_tokens, result.output_tokens)
        metrics.add_cost(cost)
        answer = result.answer
        if settings.pii_masking:
            answer = _mask_answer(logger, answer)
        return {
            "model": model_name,
            "route": route,
            "cached_calls": sum(1 for call in result.calls if call.cached),
            "cost_usd": cost,
            "answer": answer,
            "steps": result.steps,
            "tools_used": result.tools_used,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "request_id": request_id_var.get(),
        }

    return api


app = create_app()
