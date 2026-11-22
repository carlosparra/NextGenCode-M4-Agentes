"""Middleware HTTP: id por petición, log ``request``, errores y métricas."""

import re
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

REQUEST_ID_HEADER = "X-Request-ID"
REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,128}")
MILLISECONDS = 1000


def resolve_request_id(raw: str | None) -> str:
    """Usa el id del cliente si es seguro; si no, genera un UUID4.

    Un id seguro tiene de 1 a 128 caracteres ``[A-Za-z0-9._-]``; así no se pueden
    inyectar encabezados ni líneas falsas en el log.

    :param raw: Valor del encabezado ``X-Request-ID`` o ``None``
    :type raw: str or None
    :return: Id de la petición
    :rtype: str
    """
    if raw is not None and REQUEST_ID_PATTERN.fullmatch(raw):
        return raw
    return str(uuid.uuid4())


def install_observability(app: FastAPI, clock, logger, metrics) -> None:
    """Registra el middleware que observa cada petición.

    Es el único punto que atrapa excepciones: emite ``error`` con el tipo (nunca el
    mensaje) y responde ``500`` con el ``request_id``.

    :param app: Aplicación a observar
    :type app: fastapi.FastAPI
    :param clock: Reloj para medir la latencia
    :type clock: app.clock.Clock
    :param logger: Log JSON
    :type logger: app.logs.JsonLogger
    :param metrics: Métricas del proceso
    :type metrics: app.metrics.Metrics
    """

    @app.middleware("http")
    async def observe(request: Request, call_next):
        """Mide, registra y etiqueta una petición con su id."""
        request_id = resolve_request_id(request.headers.get(REQUEST_ID_HEADER))
        request.state.request_id = request_id
        start = clock.monotonic()
        try:
            response = await call_next(request)
        except Exception as error:  # pylint: disable=broad-exception-caught
            logger.emit("error", request_id, error_type=type(error).__name__)
            response = JSONResponse(
                status_code=500,
                content={"detail": "internal error", "request_id": request_id},
            )
        latency_ms = round((clock.monotonic() - start) * MILLISECONDS, 3)
        metrics.record_request(response.status_code, latency_ms)
        # Solo el nombre del cliente que dejó la dependencia de seguridad.
        client = getattr(request.state, "client", None)
        extra = {"client": client} if client is not None else {}
        logger.emit(
            "request",
            request_id,
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            latency_ms=latency_ms,
            **extra,
        )
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
