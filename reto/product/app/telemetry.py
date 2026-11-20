"""Log estructurado: un objeto JSON por linea y por evento.

Cada linea lleva ``ts`` (ISO 8601 en UTC), ``service``, ``event`` y
``request_id``. Los eventos son ``request``, ``agent_run``, ``audit`` y
``error``; los tres primeros llevan ``client`` (el nombre, nunca la clave).
Nunca se escribe el texto de preguntas ni respuestas, ni mensajes de error
completos.

El evento ``audit`` tiene una ``action``: ``tool_call`` (herramienta pedida por
el agente) o una de las guardas de seguridad (``auth_failed``,
``rate_limited``, ``input_rejected``, ``pii_detected`` y ``output_blocked``).
Las de seguridad solo llevan el tipo y donde se encontro, nunca el valor
detectado, la pregunta ni la clave.
"""

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import timezone
from typing import TextIO

from app.clock import Clock

AUDIT_TOOL_CALL = "tool_call"
AUDIT_AUTH_FAILED = "auth_failed"
AUDIT_RATE_LIMITED = "rate_limited"
AUDIT_INPUT_REJECTED = "input_rejected"
AUDIT_PII_DETECTED = "pii_detected"
AUDIT_OUTPUT_BLOCKED = "output_blocked"
SECURITY_AUDIT_ACTIONS = (
    AUDIT_AUTH_FAILED,
    AUDIT_RATE_LIMITED,
    AUDIT_INPUT_REJECTED,
    AUDIT_PII_DETECTED,
    AUDIT_OUTPUT_BLOCKED,
)
# Campos permitidos en un ``audit`` de seguridad: nunca texto de la peticion.
SECURITY_AUDIT_FIELDS = ("types", "where")


@dataclass(frozen=True)
class RunSummary:  # pylint: disable=too-many-instance-attributes
    """Resumen de una corrida del agente, solo con conteos.

    :param question_chars: Largo de la pregunta en caracteres
    :type question_chars: int
    :param history_messages: Mensajes previos recibidos
    :type history_messages: int
    :param steps: Vueltas del bucle consumidas
    :type steps: int
    :param tools: Herramientas ejecutadas, en orden
    :type tools: list[str]
    :param input_tokens: Suma de tokens de entrada
    :type input_tokens: int
    :param output_tokens: Suma de tokens de salida
    :type output_tokens: int
    :param stopped: Motivo de fin: ``answer`` o ``max_steps``
    :type stopped: str
    :param model: Nombre del modelo usado
    :type model: str
    :param route: Motivo del enrutador
    :type route: str
    :param history_sent: Mensajes de historial mandados al modelo
    :type history_sent: int
    :param cached_calls: Llamadas respondidas por la cache del gateway
    :type cached_calls: int
    :param cost_usd: Costo de la corrida en USD
    :type cost_usd: float
    :param latency_ms: Duracion de la corrida en milisegundos, medida con el
        reloj inyectado
    :type latency_ms: float
    """

    question_chars: int
    history_messages: int
    steps: int
    input_tokens: int
    output_tokens: int
    stopped: str
    tools: list = field(default_factory=list)
    model: str = ""
    route: str = ""
    history_sent: int = 0
    cached_calls: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0


class JsonLogger:
    """Escribe eventos JSON de una linea en un stream.

    :param stream: Destino del log (``sys.stdout`` en produccion)
    :type stream: typing.TextIO
    :param clock: Reloj que da la hora de cada evento
    :type clock: app.clock.Clock
    :param service: Valor del campo ``service``
    :type service: str
    """

    def __init__(self, stream: TextIO, clock: Clock, service: str):
        self._stream = stream
        self._clock = clock
        self._service = service
        self._lock = threading.Lock()

    def emit(self, event: str, request_id, fields: dict) -> None:
        """Escribe un evento como una linea JSON.

        :param event: Nombre del evento
        :type event: str
        :param request_id: Id de la peticion a la que pertenece el evento
        :type request_id: str or None
        :param fields: Campos propios del evento
        :type fields: dict
        """
        timestamp = self._clock.now().astimezone(timezone.utc).isoformat()
        record = {
            "ts": timestamp,
            "service": self._service,
            "event": event,
            "request_id": request_id,
            **fields,
        }
        line = json.dumps(record, ensure_ascii=False, default=str)
        with self._lock:
            self._stream.write(line + "\n")
            self._stream.flush()

    def bind(self, request_id: str, client=None) -> "RequestLog":
        """Devuelve un emisor ligado a una peticion.

        :param request_id: Id de la peticion
        :type request_id: str
        :param client: Nombre del cliente autenticado (nunca su clave)
        :type client: str or None
        :return: Emisor de eventos de esa peticion
        :rtype: RequestLog
        """
        return RequestLog(self, request_id, client)


class RequestLog:
    """Emisor de eventos de una sola peticion.

    :param logger: Logger que escribe las lineas
    :type logger: JsonLogger
    :param request_id: Id de la peticion
    :type request_id: str
    :param client: Nombre del cliente autenticado, si ya se conoce
    :type client: str or None
    """

    def __init__(self, logger: JsonLogger, request_id: str, client=None):
        self._logger = logger
        self.request_id = request_id
        self.client = client

    def request(  # pylint: disable=too-many-arguments
        self,
        method: str,
        path: str,
        status: int,
        latency_ms: float,
        *,
        cost_usd=None,
    ):
        """Registra una peticion HTTP atendida con el cliente ligado.

        ``client`` vale ``None`` si la peticion no se autentico.

        :param method: Metodo HTTP
        :type method: str
        :param path: Ruta pedida, sin parametros de consulta
        :type path: str
        :param status: Codigo HTTP de la respuesta
        :type status: int
        :param latency_ms: Duracion en milisegundos
        :type latency_ms: float
        :param cost_usd: Costo en USD de la respuesta (solo en ``POST /ask``);
            con ``None`` el campo no se escribe
        :type cost_usd: float or None
        """
        fields = {
            "method": method,
            "path": path,
            "status": status,
            "latency_ms": latency_ms,
            "client": self.client,
        }
        if cost_usd is not None:
            fields["cost_usd"] = cost_usd
        self._logger.emit("request", self.request_id, fields)

    def agent_run(self, summary: RunSummary) -> None:
        """Registra el resumen de una corrida del agente.

        :param summary: Conteos de la corrida, sin texto de la conversacion
        :type summary: RunSummary
        """
        fields = asdict(summary)
        fields["tools"] = list(summary.tools)
        fields["client"] = self.client
        self._logger.emit("agent_run", self.request_id, fields)

    def audit(self, tool, args, ok: bool = True) -> None:
        """Registra una llamada a herramienta pedida por el agente.

        :param tool: Nombre de la herramienta pedida
        :type tool: str
        :param args: Argumentos que pidio el modelo
        :type args: object
        :param ok: Si la herramienta se ejecuto con exito
        :type ok: bool
        """
        fields = {
            "action": AUDIT_TOOL_CALL,
            "tool": tool,
            "args": args,
            "ok": ok,
            "client": self.client,
        }
        self._logger.emit("audit", self.request_id, fields)

    def security_audit(self, action: str, **details) -> None:
        """Registra un evento ``audit`` de una guarda de seguridad.

        Solo acepta ``types`` (tipos de dato detectados) y ``where``
        (``question``, ``history`` o ``answer``): el valor detectado, la
        pregunta y la clave nunca llegan aqui.

        :param action: Una de ``SECURITY_AUDIT_ACTIONS``
        :type action: str
        :param details: ``types`` y ``where``, si aplican
        :type details: dict
        :raises ValueError: Si la accion o algun campo no estan permitidos
        """
        if action not in SECURITY_AUDIT_ACTIONS:
            raise ValueError(f"unknown security audit action: {action}")
        unknown = sorted(set(details) - set(SECURITY_AUDIT_FIELDS))
        if unknown:
            raise ValueError(f"security audit fields not allowed: {unknown}")
        fields = {"action": action, **details, "client": self.client}
        self._logger.emit("audit", self.request_id, fields)

    def error(self, error_type: str) -> None:
        """Registra un error inesperado solo con su tipo.

        :param error_type: Nombre de la clase de la excepcion
        :type error_type: str
        """
        self._logger.emit("error", self.request_id, {"error_type": error_type})


class NullRequestLog:
    """Emisor que descarta todos los eventos (uso fuera de la API)."""

    request_id = None
    client = None

    def request(  # pylint: disable=too-many-arguments
        self, method, path, status, latency_ms, *, cost_usd=None
    ) -> None:
        """No hace nada.

        :param method: Ignorado
        :param path: Ignorado
        :param status: Ignorado
        :param latency_ms: Ignorado
        :param cost_usd: Ignorado
        """

    def agent_run(self, summary) -> None:
        """No hace nada.

        :param summary: Ignorado
        """

    def audit(self, tool, args, ok: bool = True) -> None:
        """No hace nada.

        :param tool: Ignorado
        :param args: Ignorado
        :param ok: Ignorado
        """

    def security_audit(self, action, **details) -> None:
        """No hace nada.

        :param action: Ignorado
        :param details: Ignorado
        """

    def error(self, error_type) -> None:
        """No hace nada.

        :param error_type: Ignorado
        """
