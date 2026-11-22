"""Acceso por clave de cliente y límite de peticiones por minuto.

Las claves se comparan siempre con ``hmac.compare_digest`` y nunca se escriben en
el log, en la traza ni en un mensaje de error: solo viaja el nombre del cliente.
"""

import hmac
import math
import threading
from collections import deque
from collections.abc import Mapping

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader

from app.config import Secret

API_KEY_HEADER = "X-API-Key"
RETRY_AFTER_HEADER = "Retry-After"
UNAUTHORIZED_STATUS = 401
TOO_MANY_REQUESTS_STATUS = 429
UNAUTHORIZED_DETAIL = "invalid or missing API key"
RATE_LIMITED_DETAIL = "rate limit exceeded"
WINDOW_SECONDS = 60.0
MIN_RETRY_AFTER_SECONDS = 1

# auto_error=False: la ausencia de clave la responde este módulo con su propio 401.
api_key_header = APIKeyHeader(name=API_KEY_HEADER, auto_error=False)


class ApiKeyRegistry:
    """Busca el cliente dueño de una clave sin revelar cuál comparó.

    Compara contra todas las claves sin cortar en la primera coincidencia, para
    que el tiempo de respuesta no dé pistas.

    :param keys: Clave de cada cliente
    :type keys: collections.abc.Mapping[str, app.config.Secret]
    """

    def __init__(self, keys: Mapping[str, Secret]):
        self._keys = tuple(keys.items())

    def client_for(self, presented: str | None) -> str | None:
        """Devuelve el cliente dueño de la clave, o ``None`` si no es válida.

        :param presented: Clave recibida en ``X-API-Key``; puede faltar
        :type presented: str or None
        :return: Nombre del cliente o ``None``
        :rtype: str or None
        """
        if not presented:
            return None
        candidate = presented.encode("utf-8")
        owner = None
        for client, secret in self._keys:
            expected = secret.reveal().encode("utf-8")
            if hmac.compare_digest(candidate, expected):
                owner = client
        return owner


class RateLimiter:
    """Ventana deslizante de un minuto por cliente, con la hora que se le pase.

    Los rechazos no ocupan cupo. Solo guarda clientes autenticados, así que la
    memoria tiene tope en el número de clientes de ``API_KEYS``.

    :param limit_per_minute: Peticiones permitidas por cliente en la ventana
    :type limit_per_minute: int
    :param window_seconds: Largo de la ventana en segundos
    :type window_seconds: float
    """

    def __init__(self, limit_per_minute: int, window_seconds: float = WINDOW_SECONDS):
        self._limit = limit_per_minute
        self._window = window_seconds
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def _recent_hits(self, client: str, now: float) -> deque:
        """Quita las peticiones que ya salieron de la ventana y devuelve el resto.

        Debe llamarse con el candado tomado.

        :param client: Nombre del cliente
        :type client: str
        :param now: Segundos del reloj inyectado
        :type now: float
        :return: Momentos de las peticiones aceptadas dentro de la ventana
        :rtype: collections.deque
        """
        hits = self._hits.setdefault(client, deque())
        while hits and hits[0] <= now - self._window:
            hits.popleft()
        return hits

    def _seconds_to_wait(self, hits: deque, now: float) -> int:
        """Calcula cuántos segundos faltan para que se libere un lugar.

        :param hits: Peticiones aceptadas dentro de la ventana
        :type hits: collections.deque
        :param now: Segundos del reloj inyectado
        :type now: float
        :return: 0 si hay cupo; si no, segundos redondeados hacia arriba, mínimo 1
        :rtype: int
        """
        if len(hits) < self._limit:
            return 0
        remaining = hits[0] + self._window - now
        return max(MIN_RETRY_AFTER_SECONDS, math.ceil(remaining))

    def acquire(self, client: str, now: float) -> int:
        """Intenta ocupar un lugar en la ventana del cliente, de forma atómica.

        :param client: Nombre del cliente
        :type client: str
        :param now: Segundos del reloj inyectado
        :type now: float
        :return: 0 si la petición pasa; si no, segundos que debe esperar
        :rtype: int
        """
        with self._lock:
            hits = self._recent_hits(client, now)
            wait = self._seconds_to_wait(hits, now)
            if wait == 0:
                hits.append(now)
            return wait

    def allow(self, client: str, now: float) -> bool:
        """Indica si la petición pasa y, si pasa, la cuenta.

        :param client: Nombre del cliente
        :type client: str
        :param now: Segundos del reloj inyectado
        :type now: float
        :return: ``True`` si el cliente todavía tiene cupo
        :rtype: bool
        """
        return self.acquire(client, now) == 0

    def retry_after(self, client: str, now: float) -> int:
        """Devuelve los segundos que faltan para que el cliente tenga cupo.

        :param client: Nombre del cliente
        :type client: str
        :param now: Segundos del reloj inyectado
        :type now: float
        :return: 0 si ya tiene cupo; si no, segundos redondeados hacia arriba,
            nunca 0
        :rtype: int
        """
        with self._lock:
            return self._seconds_to_wait(self._recent_hits(client, now), now)


def build_client_guard(registry: ApiKeyRegistry, limiter: RateLimiter, clock):
    """Arma la dependencia de FastAPI que exige clave y respeta el límite.

    Primero valida la clave (``401``), después deja el cliente en
    ``request.state.client`` y al final aplica el límite (``429`` con
    ``Retry-After``). Ninguna respuesta ni log lleva la clave.

    :param registry: Claves por cliente
    :type registry: ApiKeyRegistry
    :param limiter: Límite por cliente
    :type limiter: RateLimiter
    :param clock: Reloj inyectado; se usa su ``monotonic()``
    :type clock: app.clock.Clock
    :return: Dependencia que devuelve el nombre del cliente
    :rtype: callable
    """

    def require_client(
        request: Request, api_key: str | None = Security(api_key_header)
    ) -> str:
        """Devuelve el cliente de la petición o responde ``401``/``429``."""
        client = registry.client_for(api_key)
        if client is None:
            raise HTTPException(
                status_code=UNAUTHORIZED_STATUS, detail=UNAUTHORIZED_DETAIL
            )
        request.state.client = client
        wait = limiter.acquire(client, clock.monotonic())
        if wait:
            raise HTTPException(
                status_code=TOO_MANY_REQUESTS_STATUS,
                detail=RATE_LIMITED_DETAIL,
                headers={RETRY_AFTER_HEADER: str(wait)},
            )
        return client

    return require_client
