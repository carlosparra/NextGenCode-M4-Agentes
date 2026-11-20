"""Limite de peticiones por cliente.

``RateLimiter(limit, clock)`` usa una ventana fija de 60 segundos por
cliente sobre ``clock.monotonic()``: la ventana empieza con la primera
peticion del cliente y, mientras dura, acepta ``limit`` peticiones.
``check(client)`` devuelve una ``RateDecision`` con ``allowed`` y, si
no se permite, ``retry_after`` en segundos enteros (1 o mas).

El estado vive en memoria, por proceso (ADR 0011): con varias copias
del servicio el limite real es ``limit`` por copia.

:seealso: ``spec/04-production.md`` (punto 2) y ADR 0011.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from typing import Protocol

WINDOW_SECONDS = 60
MIN_RETRY_AFTER = 1


class MonotonicClock(Protocol):
    """Lo unico que el limite necesita del reloj inyectado."""

    def monotonic(self) -> float:
        """Devuelve segundos de un contador que nunca retrocede.

        :return: Segundos del contador monotono.
        :rtype: float
        """


@dataclass(frozen=True)
class RateDecision:
    """Resultado de revisar el limite.

    :param allowed: ``True`` si la peticion puede pasar.
    :type allowed: bool
    :param retry_after: Segundos que faltan para la siguiente ventana;
        0 cuando se permite.
    :type retry_after: int
    """

    allowed: bool
    retry_after: int = 0


@dataclass
class _Window:
    """Ventana de un cliente: cuando empezo y cuantas peticiones lleva.

    :param started: Lectura del reloj al abrir la ventana.
    :type started: float
    :param count: Peticiones aceptadas en la ventana.
    :type count: int
    """

    started: float
    count: int = 0


class RateLimiter:
    """Limite de ``limit`` peticiones por cliente cada 60 segundos.

    :param limit: Peticiones permitidas por ventana (mayor que 0).
    :type limit: int
    :param clock: Reloj inyectado; solo se usa ``monotonic()``.
    :type clock: MonotonicClock
    """

    def __init__(self, limit: int, clock: MonotonicClock) -> None:
        """Valida el limite y prepara el estado vacio.

        :param limit: Peticiones permitidas por ventana.
        :type limit: int
        :param clock: Reloj inyectado.
        :type clock: MonotonicClock
        :raises ValueError: Si ``limit`` es menor que 1.
        """
        if limit < 1:
            raise ValueError(
                f"RATE_LIMIT_PER_MINUTE debe ser mayor que 0, se recibio: {limit}"
            )
        self._limit = limit
        self._clock = clock
        self._windows: dict[str, _Window] = {}
        # FastAPI corre las rutas sincronicas en hilos: el estado se protege.
        self._lock = threading.Lock()

    def check(self, client: str, now: float | None = None) -> RateDecision:
        """Cuenta una peticion de ``client`` si le queda cupo.

        Una peticion negada no gasta cupo.

        :param client: Nombre del cliente.
        :type client: str
        :param now: Lectura del mismo reloj al llegar la peticion (la que
            ya tomo el middleware); si falta, se lee el reloj inyectado.
        :type now: float | None
        :return: Si se permite y, si no, cuantos segundos esperar.
        :rtype: RateDecision
        """
        with self._lock:
            if now is None:
                now = self._clock.monotonic()
            window = self._windows.get(client)
            if window is None or now - window.started >= WINDOW_SECONDS:
                window = _Window(started=now)
                self._windows[client] = window
            if window.count >= self._limit:
                remaining = window.started + WINDOW_SECONDS - now
                retry_after = max(MIN_RETRY_AFTER, math.ceil(remaining))
                return RateDecision(allowed=False, retry_after=retry_after)
            window.count += 1
            return RateDecision(allowed=True)
