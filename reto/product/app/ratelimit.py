"""Limite de peticiones por cliente con ventana deslizante (ADR 0012).

El limite vive en la memoria de este proceso. El reloj se inyecta: las pruebas
usan uno que solo avanza cuando ellas lo piden.
"""

import math
import threading
from collections import deque
from dataclasses import dataclass

from app.clock import Clock

DEFAULT_WINDOW_SECONDS = 60.0
MIN_RETRY_AFTER_SECONDS = 1


@dataclass(frozen=True)
class Decision:
    """Resultado de revisar el limite.

    :param allowed: Si la peticion puede seguir
    :type allowed: bool
    :param retry_after: Segundos que faltan para que se libere un lugar
        (0 si se permite)
    :type retry_after: int
    """

    allowed: bool
    retry_after: int = 0


class RateLimiter:
    """Permite a lo mas ``limit`` peticiones por cliente en la ventana.

    Solo cuentan las peticiones permitidas; las rechazadas no alargan la
    espera. Es seguro con varios hilos.

    :param limit: Peticiones permitidas por ventana (>= 1)
    :type limit: int
    :param clock: Reloj del que se lee ``monotonic()``
    :type clock: app.clock.Clock
    :param window_seconds: Largo de la ventana en segundos
    :type window_seconds: float
    :raises ValueError: Si ``limit`` o ``window_seconds`` no son positivos
    """

    def __init__(
        self, limit: int, clock: Clock, window_seconds: float = DEFAULT_WINDOW_SECONDS
    ):
        if limit < 1 or window_seconds <= 0:
            raise ValueError("limit and window_seconds must be positive")
        self._limit = limit
        self._clock = clock
        self._window = window_seconds
        self._hits = {}
        self._lock = threading.Lock()

    def check(self, client: str) -> Decision:
        """Revisa y, si se permite, cuenta una peticion del cliente.

        :param client: Nombre del cliente ya autenticado
        :type client: str
        :return: Si se permite y, si no, cuantos segundos esperar (>= 1,
            redondeado hacia arriba)
        :rtype: Decision
        """
        with self._lock:
            now = self._clock.monotonic()
            hits = self._hits.setdefault(client, deque())
            while hits and hits[0] + self._window <= now:
                hits.popleft()
            if len(hits) < self._limit:
                hits.append(now)
                return Decision(allowed=True)
            waiting = math.ceil(hits[0] + self._window - now)
            return Decision(
                allowed=False, retry_after=max(MIN_RETRY_AFTER_SECONDS, waiting)
            )
