"""Reloj inyectable, log JSON, métricas y trazas opcionales (ADR 0005).

Los eventos llevan conteos, nunca el texto de la pregunta o de la respuesta, ni
mensajes de error completos. ``langsmith`` se importa solo si
``LANGSMITH_TRACING=true`` y hay ``LANGSMITH_API_KEY``; si no, se usa un tracer
nulo que no importa nada ni se conecta a ningún lado.
"""

import importlib
import json
import math
import sys
import time
from collections import deque
from datetime import datetime, timezone

from app.config import ConfigError

MAX_LATENCY_SAMPLES = 1000
SERVER_ERROR_STATUS = 500
LANGSMITH_MODULE = "langsmith"


class SystemClock:
    """Reloj real: hora UTC para el log y contador monótono para latencias."""

    def now(self):
        """Devuelve la hora actual en UTC.

        :return: Hora actual con zona horaria UTC
        :rtype: datetime.datetime
        """
        return datetime.now(timezone.utc)

    def monotonic(self):
        """Devuelve un contador monótono en segundos.

        :return: Segundos desde un punto fijo
        :rtype: float
        """
        return time.perf_counter()


class JsonLogger:
    """Escribe una línea JSON por evento.

    :param service: Valor del campo ``service``
    :type service: str
    :param clock: Reloj con ``now()``
    :type clock: SystemClock
    :param stream: Destino; por omisión la salida estándar del momento
    :type stream: io.TextIOBase or None
    """

    def __init__(self, service, clock, stream=None):
        self._service = service
        self._clock = clock
        self._stream = stream

    def log(self, event, request_id, **fields):
        """Escribe un evento con ``ts``, ``service``, ``event`` y ``request_id``.

        :param event: Nombre del evento (``request``, ``agent_run``, ...)
        :type event: str
        :param request_id: Id de la petición
        :type request_id: str
        :param fields: Campos propios del evento
        :type fields: dict
        """
        record = {
            "ts": self._clock.now().isoformat(),
            "service": self._service,
            "event": event,
            "request_id": request_id,
            **fields,
        }
        stream = self._stream or sys.stdout
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        stream.flush()


def percentile(values, fraction):
    """Calcula un percentil por rango más cercano.

    :param values: Muestras
    :type values: list[float]
    :param fraction: Percentil entre 0 y 1 (por ejemplo 0.95)
    :type fraction: float
    :return: El percentil; 0 si no hay muestras
    :rtype: float
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(fraction * len(ordered)))
    return float(ordered[rank - 1])


class Metrics:
    """Métricas en memoria de este proceso.

    :param slo_p95_ms: Meta de latencia p95 en milisegundos
    :type slo_p95_ms: int
    """

    def __init__(self, slo_p95_ms):
        self._slo_p95_ms = slo_p95_ms
        self._requests = 0
        self._errors = 0
        self._latencies = deque(maxlen=MAX_LATENCY_SAMPLES)
        self._input_tokens = 0
        self._output_tokens = 0
        self._cost_usd = 0.0

    def record_request(self, status, latency_ms):
        """Registra una petición atendida.

        :param status: Código HTTP de la respuesta
        :type status: int
        :param latency_ms: Latencia en milisegundos
        :type latency_ms: float
        """
        self._requests += 1
        if status >= SERVER_ERROR_STATUS:
            self._errors += 1
        self._latencies.append(latency_ms)

    def record_run(self, input_tokens, output_tokens, cost_usd):
        """Acumula tokens y costo de una corrida del agente.

        :param input_tokens: Tokens de entrada
        :type input_tokens: int
        :param output_tokens: Tokens de salida
        :type output_tokens: int
        :param cost_usd: Costo en USD
        :type cost_usd: float
        """
        self._input_tokens += input_tokens
        self._output_tokens += output_tokens
        self._cost_usd += cost_usd

    def snapshot(self, pid):
        """Devuelve las métricas actuales.

        :param pid: Id del proceso que atiende
        :type pid: int
        :return: Peticiones, errores, latencias, tokens, SLO y costo
        :rtype: dict
        """
        samples = list(self._latencies)
        p95 = percentile(samples, 0.95)
        error_rate = self._errors / self._requests if self._requests else 0.0
        return {
            "pid": pid,
            "requests": self._requests,
            "error_rate": error_rate,
            "latency_ms": {"p50": percentile(samples, 0.5), "p95": p95},
            "tokens": {"input": self._input_tokens, "output": self._output_tokens},
            "slo": {"p95_ms_target": self._slo_p95_ms, "met": p95 < self._slo_p95_ms},
            "cost_usd": self._cost_usd,
        }


class NullTracer:
    """Tracer apagado: devuelve las funciones sin cambios."""

    enabled = False

    def wrap(  # pylint: disable=too-many-arguments
        self, function, name, run_type, request_id, *, client=None
    ):
        """Devuelve ``function`` tal cual, sin trazas.

        :param function: Función que se trazaría
        :type function: callable
        :param name: Nombre de la traza
        :type name: str
        :param run_type: Tipo de traza (``chain``, ``llm`` o ``tool``)
        :type run_type: str
        :param request_id: Id de la petición
        :type request_id: str
        :param client: Nombre del cliente
        :type client: str or None
        :return: La misma función
        :rtype: callable
        """
        del name, run_type, request_id, client
        return function


class LangSmithTracer:
    """Tracer que manda cada corrida, llamada y herramienta a LangSmith.

    :param module: Módulo ``langsmith`` ya importado (o un doble de prueba)
    :type module: module
    :param client: Cliente de LangSmith con ``hide_inputs`` y ``hide_outputs``
    :type client: langsmith.Client
    """

    enabled = True

    def __init__(self, module, client):
        self._module = module
        self._client = client

    def wrap(  # pylint: disable=too-many-arguments
        self, function, name, run_type, request_id, *, client=None
    ):
        """Envuelve ``function`` con ``@traceable``, el ``request_id`` y el cliente.

        Si el tracer no puede envolverla, se devuelve la función original: una
        falla del tracer nunca tumba la petición. Solo el nombre del cliente va
        en los metadatos, nunca su clave.

        :param function: Función que se traza
        :type function: callable
        :param name: Nombre de la traza
        :type name: str
        :param run_type: Tipo de traza (``chain``, ``llm`` o ``tool``)
        :type run_type: str
        :param request_id: Id de la petición, va en los metadatos
        :type request_id: str
        :param client: Nombre del cliente; si viene, va en los metadatos
        :type client: str or None
        :return: La función trazada
        :rtype: callable
        """
        metadata = {"request_id": request_id}
        if client is not None:
            metadata["client"] = client
        try:
            traced = self._module.traceable(
                name=name,
                run_type=run_type,
                client=self._client,
                metadata=metadata,
            )(function)
        except Exception:  # pylint: disable=broad-exception-caught
            return function
        module = self._module

        def call(*args, **kwargs):
            """Ejecuta la función trazada con las trazas encendidas."""
            with module.tracing_context(enabled=True):
                return traced(*args, **kwargs)

        return call


def build_tracer(config, loader=None):
    """Crea el tracer según la configuración.

    Sin ``LANGSMITH_TRACING=true`` o sin ``LANGSMITH_API_KEY`` devuelve un
    :class:`NullTracer` y no importa ``langsmith``.

    :param config: Configuración validada
    :type config: app.config.Config
    :param loader: Función que importa un módulo por nombre; por omisión
        :func:`importlib.import_module` (se inyecta en las pruebas)
    :type loader: callable or None
    :return: El tracer a usar
    :rtype: NullTracer or LangSmithTracer
    :raises ConfigError: Si las trazas están encendidas y falta ``langsmith``
    """
    if not (config.langsmith_tracing and config.langsmith_api_key):
        return NullTracer()
    loader = loader or importlib.import_module
    try:
        module = loader(LANGSMITH_MODULE)
    except ImportError as error:
        raise ConfigError(
            "LANGSMITH_TRACING=true requiere el paquete langsmith "
            "(pip install -r requirements.txt)."
        ) from error
    client = module.Client(
        api_key=config.langsmith_api_key,
        hide_inputs=config.hide_inputs,
        hide_outputs=config.hide_outputs,
    )
    return LangSmithTracer(module, client)


class Observability:
    """Agrupa reloj, logger, métricas y tracer que recibe la app.

    :param clock: Reloj con ``now()`` y ``monotonic()``
    :type clock: SystemClock
    :param logger: Logger de eventos JSON
    :type logger: JsonLogger
    :param metrics: Métricas del proceso
    :type metrics: Metrics
    :param tracer: Tracer de LangSmith; por omisión uno nulo
    :type tracer: NullTracer or LangSmithTracer or None
    """

    def __init__(self, clock, logger, metrics, tracer=None):
        self.clock = clock
        self.logger = logger
        self.metrics = metrics
        self.tracer = tracer or NullTracer()


def build_observability(config, clock=None, stream=None, tracer=None):
    """Crea las piezas de observabilidad a partir de la configuración.

    :param config: Configuración validada
    :type config: app.config.Config
    :param clock: Reloj a usar; por omisión el reloj real
    :type clock: SystemClock or None
    :param stream: Destino del log; por omisión la salida estándar
    :type stream: io.TextIOBase or None
    :param tracer: Tracer a usar; por omisión el que indica la configuración
    :type tracer: NullTracer or LangSmithTracer or None
    :return: Reloj, logger, métricas y tracer
    :rtype: Observability
    :raises ConfigError: Si las trazas están encendidas y falta ``langsmith``
    """
    clock = clock or SystemClock()
    return Observability(
        clock=clock,
        logger=JsonLogger(config.service_name, clock, stream),
        metrics=Metrics(config.slo_p95_ms),
        tracer=tracer or build_tracer(config),
    )
