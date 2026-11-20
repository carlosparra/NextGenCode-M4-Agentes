"""Límite de peticiones por cliente con ventana deslizante (ADR 0010).

El límite vive en la memoria del proceso: con varias copias del servicio se
multiplica. El reloj se inyecta, así que las pruebas no esperan.
"""

import math
import threading
from collections import deque

WINDOW_SECONDS = 60
MIN_RETRY_AFTER_SECONDS = 1


class RateLimiter:
    """Cuenta las peticiones de cada cliente en los últimos 60 segundos.

    :param limit_per_minute: Peticiones permitidas por cliente por minuto
    :type limit_per_minute: int
    :param clock: Reloj con ``monotonic()`` en segundos
    :type clock: app.observability.SystemClock
    """

    def __init__(self, limit_per_minute, clock):
        self._limit = limit_per_minute
        self._clock = clock
        self._hits = {}
        self._lock = threading.Lock()

    def check(self, client):
        """Registra una petición del cliente si cabe en su cupo.

        Un rechazo no consume cupo.

        :param client: Nombre del cliente
        :type client: str
        :return: ``None`` si la petición pasa; si no, los segundos que faltan
            para que se libere un lugar (redondeados hacia arriba, mínimo 1)
        :rtype: int or None
        """
        now = self._clock.monotonic()
        with self._lock:
            hits = self._hits.setdefault(client, deque())
            while hits and now - hits[0] >= WINDOW_SECONDS:
                hits.popleft()
            if len(hits) >= self._limit:
                remaining = WINDOW_SECONDS - (now - hits[0])
                return max(MIN_RETRY_AFTER_SECONDS, math.ceil(remaining))
            hits.append(now)
            return None
