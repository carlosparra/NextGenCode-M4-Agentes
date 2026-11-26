"""Quién puede entrar: clave por cliente, permisos y límite de peticiones."""

import hmac
import threading
from collections import defaultdict, deque

from app.config import Settings

WINDOW_SECONDS = 60


class Authenticator:
    """Reconoce al cliente por su clave y dice qué puede hacer."""

    def __init__(self, settings: Settings):
        self._settings = settings

    def identify(self, key: str | None) -> str | None:
        """Devuelve el cliente dueño de la clave.

        Compara contra todas las claves en tiempo constante, para que el tiempo de
        respuesta no revele cuál estuvo cerca.

        :param key: Valor del encabezado ``X-API-Key``
        :type key: str | None
        :return: Nombre del cliente, o ``None`` si la clave no es válida
        :rtype: str | None
        """
        found = None
        candidate = (key or "").encode("utf-8")
        for client, expected in self._settings.api_keys.items():
            if hmac.compare_digest(candidate, expected.encode("utf-8")):
                found = client
        return found

    def allowed(self, client: str, scope: str) -> bool:
        """Indica si el cliente tiene un permiso.

        :param client: Nombre del cliente
        :type client: str
        :param scope: ``ask``, ``mcp`` o ``metrics``
        :type scope: str
        :return: ``True`` si puede
        :rtype: bool
        """
        return scope in self._settings.scopes_for(client)


class RateLimiter:
    """Ventana deslizante de un minuto por cliente, en memoria de este proceso."""

    def __init__(self, limit: int, clock):
        self._limit = limit
        self._clock = clock
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def retry_after(self, client: str) -> int:
        """Registra una petición y dice si pasa.

        :param client: Nombre del cliente
        :type client: str
        :return: 0 si pasa; si no, los segundos que faltan para volver a intentar
        :rtype: int
        """
        now = self._clock.now().timestamp()
        with self._lock:
            hits = self._hits[client]
            while hits and now - hits[0] >= WINDOW_SECONDS:
                hits.popleft()
            if len(hits) >= self._limit:
                return max(1, int(WINDOW_SECONDS - (now - hits[0]) + 0.999))
            hits.append(now)
            return 0
