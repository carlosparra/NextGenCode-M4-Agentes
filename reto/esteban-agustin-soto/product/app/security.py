"""Claves por cliente y límite de peticiones por minuto.

Ninguna función de este módulo escribe, devuelve en un mensaje ni registra el
valor de una clave: los errores solo dicen la posición de la entrada y su largo.
"""

import hmac
import math
import threading

WINDOW_SECONDS = 60


def _entry_error(position, entry, reason):
    """Arma un error sin el valor de la entrada.

    :param position: Posición de la entrada, desde 1
    :type position: int
    :param entry: Entrada con problema (solo se usa su largo)
    :type entry: str
    :param reason: Qué falla
    :type reason: str
    :return: El error a lanzar
    :rtype: ValueError
    """
    return ValueError(
        f"API_KEYS entry {position} is malformed ({reason}); "
        f"entry length is {len(entry)}"
    )


def parse_api_keys(raw):
    """Convierte ``cliente:clave,cliente2:clave2`` en un diccionario.

    La clave puede contener ``:``; se separa en el primero. Los espacios
    alrededor de cada parte se ignoran.

    :param raw: Valor de ``API_KEYS``
    :type raw: str
    :return: Diccionario ``cliente -> clave``
    :rtype: dict
    :raises ValueError: Si una entrada no tiene la forma, tiene el cliente o la
        clave vacíos, o repite un cliente; el mensaje no trae el valor
    """
    keys = {}
    if not raw or not raw.strip():
        return keys
    for position, entry in enumerate(raw.split(","), start=1):
        name, separator, key = entry.partition(":")
        name, key = name.strip(), key.strip()
        if not separator:
            raise _entry_error(position, entry, "expected client:key")
        if not name or not key:
            raise _entry_error(position, entry, "empty client or key")
        if name in keys:
            raise _entry_error(position, entry, "client is repeated")
        keys[name] = key
    return keys


def authenticate(api_keys, received):
    """Busca a qué cliente pertenece la clave recibida.

    Compara contra todas las claves con ``hmac.compare_digest`` y no corta en
    el primer acierto, para no filtrar información por el tiempo.

    :param api_keys: Diccionario ``cliente -> clave``
    :type api_keys: dict
    :param received: Valor del encabezado ``X-API-Key`` o ``None``
    :type received: str or None
    :return: El nombre del cliente o ``None``
    :rtype: str or None
    """
    if not received:
        return None
    candidate = received.encode("utf-8")
    found = None
    for name, key in api_keys.items():
        if hmac.compare_digest(candidate, key.encode("utf-8")):
            found = name
    return found


class RateLimiter:
    """Ventana fija de un minuto por cliente, en memoria de este proceso.

    :param limit: Peticiones permitidas por minuto y cliente
    :type limit: int
    :param clock: Objeto con ``now()`` que devuelve un ``datetime``
    :type clock: object
    """

    def __init__(self, limit, clock):
        self._limit = limit
        self._clock = clock
        self._lock = threading.Lock()
        self._windows = {}

    def check(self, client):
        """Cuenta una petición del cliente.

        :param client: Nombre del cliente ya autenticado
        :type client: str
        :return: ``None`` si pasa; si no, los segundos que faltan (1 a 60)
        :rtype: int or None
        """
        seconds = self._clock.now().timestamp()
        window = int(seconds // WINDOW_SECONDS)
        with self._lock:
            current, count = self._windows.get(client, (window, 0))
            if current != window:
                current, count = window, 0
            if count >= self._limit:
                self._windows[client] = (current, count)
                return max(1, math.ceil(WINDOW_SECONDS - seconds % WINDOW_SECONDS))
            self._windows[client] = (current, count + 1)
            return None
