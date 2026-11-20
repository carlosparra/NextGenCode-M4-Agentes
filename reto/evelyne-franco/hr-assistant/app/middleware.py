"""Middleware ASGI de observabilidad.

Para cada peticion HTTP: resuelve el ``request_id`` (encabezado
``X-Request-ID`` valido o un UUID nuevo), mide la latencia con el
reloj inyectado, agrega ``X-Request-ID`` a la respuesta, emite el
evento ``request`` y alimenta las metricas. Si algo truena, emite
``error`` solo con el tipo y responde 500 con el ``request_id``.

Desde la sesion 4, si la dependencia de autenticacion dejo el
``client`` en ``scope["state"]``, el evento ``request`` lo incluye.
El middleware nunca lee ni registra ``X-API-Key``.

:seealso: ``spec/02-observability.md`` y ADR 0004.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.clock import Clock
from app.logs import JsonLogger
from app.metrics import Metrics

REQUEST_ID_HEADER = "X-Request-ID"
# Solo se acepta un id corto y sin caracteres raros (evita inyeccion en logs).
VALID_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")
INTERNAL_ERROR_STATUS = 500
MS_PER_SECOND = 1000
# Llave de ``scope["state"]`` donde ``app.main`` deja el cliente autenticado.
CLIENT_STATE_KEY = "client"
# Lectura del reloj monotono al llegar la peticion (la reusa el limite).
STARTED_STATE_KEY = "started_monotonic"


def resolve_request_id(candidate: str | None) -> str:
    """Devuelve el id del cliente si es valido o uno nuevo (UUID4).

    :param candidate: Valor del encabezado ``X-Request-ID``.
    :type candidate: str | None
    :return: Id de la peticion.
    :rtype: str
    """
    if candidate and VALID_REQUEST_ID.fullmatch(candidate):
        return candidate
    return str(uuid.uuid4())


def request_id_of(scope: Scope) -> str:
    """Lee el ``request_id`` que el middleware guardo en el scope.

    :param scope: Scope ASGI de la peticion.
    :type scope: starlette.types.Scope
    :return: Id de la peticion o ``-`` si no existe.
    :rtype: str
    """
    return scope.get("state", {}).get("request_id", "-")


def started_of(scope: Scope) -> float | None:
    """Lee la hora monotona de llegada que el middleware guardo.

    :param scope: Scope ASGI de la peticion.
    :type scope: starlette.types.Scope
    :return: Lectura de ``clock.monotonic()`` o ``None`` si no existe.
    :rtype: float | None
    """
    return scope.get("state", {}).get(STARTED_STATE_KEY)


def client_of(scope: Scope) -> str | None:
    """Lee el cliente que la autenticacion guardo en el scope.

    Solo existe si la peticion traia una clave valida. La clave nunca
    se guarda en el scope ni se lee aqui.

    :param scope: Scope ASGI de la peticion.
    :type scope: starlette.types.Scope
    :return: Nombre del cliente o ``None``.
    :rtype: str | None
    """
    return scope.get("state", {}).get(CLIENT_STATE_KEY)


class ObservabilityMiddleware:
    """Middleware ASGI que da id, log, metricas y manejo de errores.

    :param app: Aplicacion ASGI envuelta.
    :type app: starlette.types.ASGIApp
    :param logger: Logger de eventos JSON.
    :type logger: app.logs.JsonLogger
    :param metrics: Metricas del proceso.
    :type metrics: app.metrics.Metrics
    :param clock: Reloj para medir la latencia.
    :type clock: app.clock.Clock
    """

    def __init__(
        self,
        app: ASGIApp,
        logger: JsonLogger,
        metrics: Metrics,
        clock: Clock,
    ) -> None:
        """Guarda la aplicacion y sus dependencias.

        :param app: Aplicacion ASGI envuelta.
        :type app: starlette.types.ASGIApp
        :param logger: Logger de eventos JSON.
        :type logger: app.logs.JsonLogger
        :param metrics: Metricas del proceso.
        :type metrics: app.metrics.Metrics
        :param clock: Reloj para medir la latencia.
        :type clock: app.clock.Clock
        """
        self._app = app
        self._logger = logger
        self._metrics = metrics
        self._clock = clock

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Atiende una peticion ASGI.

        :param scope: Scope ASGI.
        :type scope: starlette.types.Scope
        :param receive: Canal de entrada ASGI.
        :type receive: starlette.types.Receive
        :param send: Canal de salida ASGI.
        :type send: starlette.types.Send
        """
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        started = self._clock.monotonic()
        request_id = resolve_request_id(Headers(scope=scope).get(REQUEST_ID_HEADER))
        state = scope.setdefault("state", {})
        state["request_id"] = request_id
        state[STARTED_STATE_KEY] = started
        response: dict[str, Any] = {"status": INTERNAL_ERROR_STATUS, "sent": False}

        async def send_with_id(message: Message) -> None:
            """Agrega ``X-Request-ID`` y anota el status de la respuesta.

            :param message: Mensaje ASGI de salida.
            :type message: starlette.types.Message
            """
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message).append(REQUEST_ID_HEADER, request_id)
                response["status"] = message["status"]
                response["sent"] = True
            await send(message)

        try:
            await self._app(scope, receive, send_with_id)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # Solo el tipo: el mensaje puede traer datos sensibles.
            self._logger.emit("error", request_id, error_type=type(exc).__name__)
            if not response["sent"]:
                await self._internal_error(request_id)(scope, receive, send_with_id)
            response["status"] = INTERNAL_ERROR_STATUS
        finally:
            self._finish(scope, request_id, response["status"], started)

    @staticmethod
    def _internal_error(request_id: str) -> JSONResponse:
        """Construye la respuesta 500 generica.

        :param request_id: Id de la peticion.
        :type request_id: str
        :return: Respuesta con ``detail`` y ``request_id``.
        :rtype: starlette.responses.JSONResponse
        """
        return JSONResponse(
            {"detail": "internal error", "request_id": request_id},
            status_code=INTERNAL_ERROR_STATUS,
        )

    def _finish(
        self, scope: Scope, request_id: str, status: int, started: float
    ) -> None:
        """Emite el evento ``request`` y registra la peticion.

        :param scope: Scope ASGI de la peticion.
        :type scope: starlette.types.Scope
        :param request_id: Id de la peticion.
        :type request_id: str
        :param status: Codigo HTTP de la respuesta.
        :type status: int
        :param started: Lectura del reloj monotono al empezar.
        :type started: float
        """
        latency_ms = round((self._clock.monotonic() - started) * MS_PER_SECOND, 3)
        fields: dict[str, Any] = {
            "method": scope.get("method", ""),
            "path": scope.get("path", ""),
            "status": status,
            "latency_ms": latency_ms,
        }
        client = client_of(scope)
        if client is not None:
            fields["client"] = client
        self._logger.emit("request", request_id, **fields)
        self._metrics.record_request(latency_ms, status)
