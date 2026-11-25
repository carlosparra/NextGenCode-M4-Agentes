"""Control de acceso: clave por cliente, permisos y límite de peticiones."""

from __future__ import annotations

import hmac
import math
import threading
from collections import deque

from app.clock import Clock
from app.config import ApiClient


class Authenticator:
    """Identifica al cliente a partir de su clave.

    :param clients: Clientes autorizados
    :type clients: tuple[ApiClient, ...]
    """

    def __init__(self, clients: tuple[ApiClient, ...]) -> None:
        self._clients = clients

    def identify(self, presented: str | None) -> ApiClient | None:
        """Devuelve el cliente dueño de la clave, comparando en tiempo constante.

        :param presented: Clave recibida (puede faltar)
        :type presented: str | None
        :return: El cliente, o ``None`` si la clave falta o no es válida
        :rtype: ApiClient | None
        """
        if not presented:
            return None
        given = presented.encode("utf-8")
        match = None
        for client in self._clients:
            # Se comparan todas para no filtrar por tiempo cuál coincidió
            if hmac.compare_digest(given, client.key.encode("utf-8")):
                match = client
        return match


def extract_key(headers) -> str | None:
    """Lee la clave de ``X-API-Key`` o de ``Authorization: Bearer``.

    :param headers: Encabezados de la petición
    :type headers: Mapping[str, str]
    :return: La clave, si viene
    :rtype: str | None
    """
    key = headers.get("x-api-key")
    if key:
        return key
    auth = headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return None


class RateLimiter:
    """Ventana deslizante de 60 segundos por cliente, con reloj inyectado.

    :param per_minute: Peticiones permitidas por minuto
    :type per_minute: int
    :param clock: Reloj para medir el tiempo
    :type clock: Clock
    """

    WINDOW = 60.0

    def __init__(self, per_minute: int, clock: Clock) -> None:
        self._limit = per_minute
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, client: str) -> int:
        """Registra una petición y dice cuánto esperar si se pasó del límite.

        :param client: Nombre del cliente
        :type client: str
        :return: 0 si puede pasar; si no, segundos que faltan (al menos 1)
        :rtype: int
        """
        now = self._clock.now().timestamp()
        with self._lock:
            hits = self._hits.setdefault(client, deque())
            while hits and now - hits[0] >= self.WINDOW:
                hits.popleft()
            if len(hits) >= self._limit:
                return max(1, math.ceil(self.WINDOW - (now - hits[0])))
            hits.append(now)
            return 0
