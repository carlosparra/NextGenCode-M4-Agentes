"""Auditoria de seguridad del HR Assistant.

``SecurityAudit.record`` deja constancia de cada deteccion en tres
lugares, con los mismos cinco campos (``request_id``, ``client``,
``stage``, ``control`` y ``kinds``):

- Un evento ``security`` en el log JSON.
- Un conteo por control en ``app.metrics.Metrics``.
- Un span ``security`` en el trazador inyectado, con los campos como
  metadatos.

La firma no recibe ningun texto: el valor detectado no puede llegar al
log, a la metrica ni a la traza.

:seealso: ``spec/05-security-hardening.md``, punto 6.
"""

from __future__ import annotations

from typing import Any, Protocol

from app.logs import JsonLogger, NullLogger
from app.metrics import Metrics

SECURITY_EVENT = "security"
STAGE_INPUT = "input"
STAGE_OUTPUT = "output"


class Audit(Protocol):  # pylint: disable=too-few-public-methods
    """Interfaz de la auditoria que usan el agente y la API."""

    # pylint: disable-next=too-many-arguments,too-many-positional-arguments
    def record(
        self,
        request_id: str,
        client: str,
        stage: str,
        control: str,
        kinds: list[str],
    ) -> None:
        """Registra una deteccion.

        :param request_id: Id de la peticion.
        :type request_id: str
        :param client: Cliente que pregunta (nunca su clave).
        :type client: str
        :param stage: ``input`` u ``output``.
        :type stage: str
        :param control: ``pii``, ``secret``, ``output_invalid``,
            ``tool_args`` o ``injection``.
        :type control: str
        :param kinds: Tipos detectados.
        :type kinds: list[str]
        """


class NullAudit:  # pylint: disable=too-few-public-methods
    """Auditoria que descarta todo; util cuando no se inyecta una."""

    # pylint: disable-next=too-many-arguments,too-many-positional-arguments
    def record(
        self,
        request_id: str,
        client: str,
        stage: str,
        control: str,
        kinds: list[str],
    ) -> None:
        """No hace nada.

        :param request_id: Id de la peticion (ignorado).
        :type request_id: str
        :param client: Cliente (ignorado).
        :type client: str
        :param stage: Etapa (ignorada).
        :type stage: str
        :param control: Control (ignorado).
        :type control: str
        :param kinds: Tipos (ignorados).
        :type kinds: list[str]
        """


class SecurityAudit:  # pylint: disable=too-few-public-methods
    """Escribe cada deteccion en el log, las metricas y la traza.

    :param logger: Logger de eventos JSON.
    :type logger: app.logs.JsonLogger | app.logs.NullLogger
    :param metrics: Metricas del proceso.
    :type metrics: app.metrics.Metrics
    :param tracer: Trazador con ``traceable(name, run_type, metadata)``.
    :type tracer: app.tracing.Tracer
    """

    def __init__(
        self, logger: JsonLogger | NullLogger, metrics: Metrics, tracer: Any
    ) -> None:
        """Guarda el logger, las metricas y el trazador.

        :param logger: Logger de eventos JSON.
        :type logger: app.logs.JsonLogger | app.logs.NullLogger
        :param metrics: Metricas del proceso.
        :type metrics: app.metrics.Metrics
        :param tracer: Trazador inyectado.
        :type tracer: app.tracing.Tracer
        """
        self._logger = logger
        self._metrics = metrics
        self._tracer = tracer

    # pylint: disable-next=too-many-arguments,too-many-positional-arguments
    def record(
        self,
        request_id: str,
        client: str,
        stage: str,
        control: str,
        kinds: list[str],
    ) -> None:
        """Registra una deteccion sin el valor detectado.

        :param request_id: Id de la peticion.
        :type request_id: str
        :param client: Cliente que pregunta (nunca su clave).
        :type client: str
        :param stage: ``input`` u ``output``.
        :type stage: str
        :param control: Control que detecto algo.
        :type control: str
        :param kinds: Tipos detectados.
        :type kinds: list[str]
        """
        event = {"client": client, "stage": stage}
        event.update(control=control, kinds=list(kinds))
        self._logger.emit(SECURITY_EVENT, request_id, **event)
        self._metrics.record_security(control)
        metadata = {"request_id": request_id, **event}
        span = self._tracer.traceable(SECURITY_EVENT, "chain", metadata)(
            _security_span
        )
        span()


def _security_span() -> None:
    """Cuerpo vacio del span ``security``: los datos van en los metadatos.

    :return: Nada.
    :rtype: None
    """
    return None
