"""API web sin estado del HR Assistant: log JSON, métricas, trazas, costos y PII."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field, StringConstraints

from app import compliance, pii
from app.agent import Agent, AgentResult
from app.clock import SystemClock
from app.config import Settings, load_settings
from app.directory import EmployeeDirectory
from app.gateway import ModelUnavailableError
from app.llm import LanguageModel, build_models
from app.logs import JsonLogger
from app.metrics import Metrics
from app.middleware import install_observability
from app.output_filter import clean_answer
from app.pricing import PriceTable
from app.routing import Route, choose_model, window_history
from app.security import ApiKeyRegistry, RateLimiter, build_client_guard
from app.tracing import Tracer

PAGE_PATH = Path(__file__).resolve().parent / "static" / "index.html"
MODEL_UNAVAILABLE_STATUS = 502
COST_DECIMALS = 10


class AskResponse(BaseModel):
    """Respuesta de ``POST /ask``.

    :param answer: Respuesta en español
    :type answer: str
    :param steps: Número de vueltas del agente
    :type steps: int
    :param tools_used: Herramientas usadas
    :type tools_used: list[str]
    :param input_tokens: Tokens de entrada
    :type input_tokens: int
    :param output_tokens: Tokens de salida
    :type output_tokens: int
    :param request_id: Id de la petición, para pasarlo a soporte
    :type request_id: str
    :param model: Modelo que respondió
    :type model: str
    :param route: Motivo del enrutador
    :type route: str
    :param cached_calls: Llamadas que salieron de la caché del gateway
    :type cached_calls: int
    :param cost_usd: Costo de la respuesta en USD
    :type cost_usd: float
    :param pii_redacted: Tipos de PII ocultados en la pregunta, sin valores
    :type pii_redacted: list[str]
    """

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
    pii_redacted: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class Observability:
    """Piezas de observabilidad que comparten las rutas.

    :param logger: Log JSON
    :type logger: app.logs.JsonLogger
    :param metrics: Métricas del proceso
    :type metrics: app.metrics.Metrics
    :param tracer: Trazas opcionales en LangSmith
    :type tracer: app.tracing.Tracer
    """

    logger: JsonLogger
    metrics: Metrics
    tracer: Tracer


@dataclass(frozen=True)
class Assistant:
    """Lo que necesita ``POST /ask`` para responder y cobrar.

    :param agent: Agente con los modelos por nombre
    :type agent: app.agent.Agent
    :param settings: Configuración validada
    :type settings: app.config.Settings
    :param prices: Tabla de precios
    :type prices: app.pricing.PriceTable
    """

    agent: Agent
    settings: Settings
    prices: PriceTable


def _build_request_models(max_chars: int):
    """Arma los modelos de petición con el largo máximo configurado.

    :param max_chars: Largo máximo de la pregunta y de cada turno
    :type max_chars: int
    :return: Modelo del turno de historial y modelo de la petición
    :rtype: tuple[type, type]
    """
    text = Annotated[
        str, StringConstraints(min_length=1, max_length=max_chars, pattern=r"\S")
    ]

    class HistoryTurn(BaseModel):
        """Turno previo de la conversación enviado por el cliente."""

        role: Literal["user", "assistant"]
        content: text

    class AskRequest(BaseModel):
        """Cuerpo de ``POST /ask``."""

        question: text
        history: list[HistoryTurn] = Field(default_factory=list)

    return HistoryTurn, AskRequest


def _resolve_models(settings: Settings, model, models, directory) -> dict:
    """Decide qué modelos usa la aplicación.

    Si se inyecta un solo ``model``, sirve para ambos nombres: el costo se sigue
    calculando con el nombre que eligió el enrutador.

    :param settings: Configuración validada
    :type settings: app.config.Settings
    :param model: Modelo único inyectado, o ``None``
    :type model: app.llm.LanguageModel or None
    :param models: Modelos por nombre inyectados, o ``None``
    :type models: dict or None
    :param directory: Directorio de empleados
    :type directory: app.directory.EmployeeDirectory
    :return: Modelo por nombre
    :rtype: dict[str, app.llm.LanguageModel]
    """
    if models is not None:
        return dict(models)
    if model is not None:
        names = (settings.costs.model_small, settings.costs.model_large)
        return {name: model for name in names}
    return build_models(settings, directory)


def create_app(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    settings: Settings | None = None,
    model: LanguageModel | None = None,
    directory: EmployeeDirectory | None = None,
    clock=None,
    log_stream=None,
    models: dict | None = None,
) -> FastAPI:
    """Crea la aplicación con sus dependencias (por omisión desde el entorno).

    :param settings: Configuración; si falta se lee de ``os.environ``
    :type settings: app.config.Settings or None
    :param model: Modelo único para ambos nombres; si falta se construyen según la
        configuración
    :type model: app.llm.LanguageModel or None
    :param directory: Directorio de empleados; si falta se carga del archivo
    :type directory: app.directory.EmployeeDirectory or None
    :param clock: Reloj para el log y la latencia; por omisión el del sistema
    :type clock: app.clock.Clock or None
    :param log_stream: Flujo del log JSON; por omisión la salida estándar
    :type log_stream: typing.TextIO or None
    :param models: Modelos por nombre (``MODEL_SMALL`` y ``MODEL_LARGE``)
    :type models: dict[str, app.llm.LanguageModel] or None
    :return: Aplicación FastAPI lista para servir
    :rtype: fastapi.FastAPI
    :raises app.config.ConfigError: Si la configuración no es válida, incumple
        las reglas de producción o algún modelo no tiene precio
    """
    settings = settings or load_settings(os.environ)
    # Antes de construir nada: producción insegura no arranca.
    compliance.check(settings)
    prices = PriceTable.load(settings.costs.prices_path)
    prices.require([settings.costs.model_small, settings.costs.model_large])
    directory = directory or EmployeeDirectory(settings.employees_path)
    clock = clock or SystemClock()
    observability = Observability(
        logger=JsonLogger(settings.service_name, clock, stream=log_stream),
        metrics=Metrics(slo_p95_ms=settings.slo_p95_ms),
        tracer=Tracer(settings),
    )
    agent = Agent(
        _resolve_models(settings, model, models, directory),
        directory,
        max_steps=settings.agent_max_steps,
        tracer=observability.tracer,
    )
    page = PAGE_PATH.read_text(encoding="utf-8")
    guard = build_client_guard(
        ApiKeyRegistry(settings.api_keys),
        RateLimiter(settings.rate_limit_per_minute),
        clock,
    )

    app = FastAPI(title="HR Assistant")
    install_observability(app, clock, observability.logger, observability.metrics)
    _register_model_unavailable(app, observability.logger)

    @app.get("/", response_class=HTMLResponse)
    def home() -> HTMLResponse:
        """Sirve la página web."""
        return HTMLResponse(page)

    @app.get("/health")
    def health() -> dict:
        """Indica que el proceso está vivo."""
        return {"status": "ok", "pid": os.getpid()}

    @app.get("/metrics", dependencies=[Depends(guard)])
    def read_metrics() -> dict:
        """Devuelve las métricas de este proceso; exige ``X-API-Key``."""
        return observability.metrics.snapshot()

    _register_ask(app, Assistant(agent, settings, prices), observability, guard)
    return app


def _register_model_unavailable(app: FastAPI, logger: JsonLogger) -> None:
    """Convierte ``ModelUnavailableError`` en ``502`` con el ``request_id``.

    Registra un evento ``error`` con el tipo de la excepción, nunca su mensaje.

    :param app: Aplicación donde se registra el manejador
    :type app: fastapi.FastAPI
    :param logger: Log JSON
    :type logger: app.logs.JsonLogger
    """

    @app.exception_handler(ModelUnavailableError)
    async def model_unavailable(request: Request, error: Exception) -> JSONResponse:
        """Responde ``502`` cuando el modelo no está disponible."""
        request_id = request.state.request_id
        logger.emit("error", request_id, error_type=type(error).__name__)
        return JSONResponse(
            status_code=MODEL_UNAVAILABLE_STATUS,
            content={"detail": "model unavailable", "request_id": request_id},
        )


def _log_agent_run(logger, request_id: str, run: dict) -> None:
    """Emite ``agent_run`` solo con números y nombres, nunca con textos.

    :param logger: Log JSON
    :type logger: app.logs.JsonLogger
    :param request_id: Id de la petición
    :type request_id: str
    :param run: Cliente, pregunta, historial, ruta, resultado y costo de la corrida
    :type run: dict
    """
    result: AgentResult = run["result"]
    route: Route = run["route"]
    logger.emit(
        "agent_run",
        request_id,
        client=run["client"],
        question_chars=len(run["question"]),
        history_messages=run["history_messages"],
        history_sent=run["history_sent"],
        model=route.model,
        route=route.reason,
        steps=result.steps,
        tools=list(result.tools_used),
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cached_calls=result.cached_calls,
        cost_usd=run["cost_usd"],
        stopped=result.stopped,
    )


def _response_cost(prices: PriceTable, model: str, result: AgentResult) -> float:
    """Calcula el costo de una respuesta con los tokens cobrables, redondeado.

    :param prices: Tabla de precios
    :type prices: app.pricing.PriceTable
    :param model: Modelo que eligió el enrutador
    :type model: str
    :param result: Resultado de la corrida del agente
    :type result: app.agent.AgentResult
    :return: Costo en USD
    :rtype: float
    """
    cost = prices.cost_usd(
        model, result.billable_input_tokens, result.billable_output_tokens
    )
    return round(cost, COST_DECIMALS)


def _record_usage(metrics: Metrics, result: AgentResult, cost_usd: float) -> None:
    """Suma tokens y costo de la respuesta a las métricas del proceso.

    :param metrics: Métricas del proceso
    :type metrics: app.metrics.Metrics
    :param result: Resultado de la corrida del agente
    :type result: app.agent.AgentResult
    :param cost_usd: Costo de la respuesta en USD
    :type cost_usd: float
    """
    metrics.add_tokens(result.input_tokens, result.output_tokens)
    metrics.add_cost(cost_usd)


def _redact_input(question: str, history: list, enabled: bool) -> tuple:
    """Redacta la PII de la pregunta y de cada turno del historial.

    Solo los tipos de la pregunta se informan: el historial lo reenvía el
    navegador y contarlo otra vez duplicaría las detecciones.

    :param question: Pregunta original
    :type question: str
    :param history: Turnos previos con ``role`` y ``content``
    :type history: list[dict]
    :param enabled: Valor de ``PII_REDACTION``; con ``False`` no se toca nada
    :type enabled: bool
    :return: Pregunta redactada, historial redactado y tipos de la pregunta
    :rtype: tuple[str, list[dict], list[str]]
    """
    if not enabled:
        return question, history, []
    redacted_question, types = pii.redact(question)
    redacted_history = [
        {**turn, "content": pii.redact(turn["content"])[0]} for turn in history
    ]
    return redacted_question, redacted_history, types


def _report_pii(observability, request_id: str, client: str, found: tuple) -> None:
    """Emite ``pii_detected`` y suma las métricas si hubo PII.

    El evento lleva la dirección y los tipos, nunca el valor detectado.

    :param observability: Log, métricas y trazador de la aplicación
    :type observability: Observability
    :param request_id: Id de la petición
    :type request_id: str
    :param client: Cliente que hizo la petición
    :type client: str
    :param found: Dirección (``input`` u ``output``) y tipos encontrados
    :type found: tuple[str, list[str]]
    """
    direction, types = found
    if not types:
        return
    observability.logger.emit(
        "pii_detected",
        request_id,
        client=client,
        direction=direction,
        types=list(types),
    )
    observability.metrics.record_pii(direction, types)


def _build_response(
    request_id: str,
    route: Route,
    result: AgentResult,
    cost_usd: float,
    pii_redacted: list,
) -> AskResponse:
    """Arma la respuesta de ``POST /ask``.

    :param request_id: Id de la petición
    :type request_id: str
    :param route: Modelo elegido y motivo
    :type route: app.routing.Route
    :param result: Resultado de la corrida del agente, con la respuesta ya
        filtrada
    :type result: app.agent.AgentResult
    :param cost_usd: Costo de la respuesta en USD
    :type cost_usd: float
    :param pii_redacted: Tipos de PII ocultados en la pregunta
    :type pii_redacted: list[str]
    :return: Respuesta lista para serializar
    :rtype: AskResponse
    """
    return AskResponse(
        answer=result.answer,
        steps=result.steps,
        tools_used=list(result.tools_used),
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        request_id=request_id,
        model=route.model,
        route=route.reason,
        cached_calls=result.cached_calls,
        cost_usd=cost_usd,
        pii_redacted=list(pii_redacted),
    )


def _register_ask(
    app: FastAPI, assistant: Assistant, observability, guard
) -> None:
    """Registra ``POST /ask``: redacta, enruta, recorta, responde, filtra y cobra.

    Exige ``X-API-Key`` y respeta el límite por cliente antes de validar el
    cuerpo. Con ``PII_REDACTION`` redacta la pregunta y el historial antes del
    enrutador y del agente, y filtra la respuesta antes de devolverla; cada
    detección emite ``pii_detected`` (solo tipos). Emite ``audit`` y
    ``agent_run`` con el cliente y suma tokens y costo.
    Si el modelo no está disponible responde ``502``; los demás errores los
    atrapa el middleware.

    :param app: Aplicación donde se registra la ruta
    :type app: fastapi.FastAPI
    :param assistant: Agente, configuración y precios
    :type assistant: Assistant
    :param observability: Log, métricas y trazador de la aplicación
    :type observability: Observability
    :param guard: Dependencia que devuelve el cliente o responde ``401``/``429``
    :type guard: callable
    """
    settings = assistant.settings
    _, ask_request = _build_request_models(settings.max_question_chars)
    logger = observability.logger

    @app.post("/ask", response_model=AskResponse)
    def ask(
        payload: ask_request,  # type: ignore[valid-type]
        request: Request,
        client: Annotated[str, Depends(guard)],
    ):
        """Responde una pregunta sin guardar nada entre peticiones."""
        request_id = request.state.request_id
        # Desde aquí nadie ve el texto original: ni el modelo, ni la caché, ni la
        # traza, ni el log.
        question, history, input_types = _redact_input(
            payload.question,
            [turn.model_dump() for turn in payload.history],
            settings.pii_redaction,
        )
        _report_pii(observability, request_id, client, ("input", input_types))
        sent = window_history(history, settings.costs.history_window)
        route = choose_model(question, settings)

        def audit(tool: str, args: dict) -> None:
            logger.emit(
                "audit",
                request_id,
                client=client,
                action="tool_call",
                tool=tool,
                args=args,
            )

        with observability.tracer.request_scope(request_id, client):
            result = assistant.agent.run(
                question, sent, on_tool_call=audit, model_name=route.model
            )
        result.answer, output_types = clean_answer(
            result.answer,
            settings.max_answer_chars,
            pii.redact if settings.pii_redaction else None,
        )
        _report_pii(observability, request_id, client, ("output", output_types))
        cost_usd = _response_cost(assistant.prices, route.model, result)
        _log_agent_run(
            logger,
            request_id,
            {
                "client": client,
                "question": question,
                "history_messages": len(history),
                "history_sent": len(sent),
                "route": route,
                "result": result,
                "cost_usd": cost_usd,
            },
        )
        _record_usage(observability.metrics, result, cost_usd)
        return _build_response(request_id, route, result, cost_usd, input_types)


app = create_app()
