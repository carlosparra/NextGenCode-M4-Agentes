"""Claves por cliente y la dependencia que protege las rutas (ADR 0009).

La clave nunca sale de este módulo: los errores dan la posición y el largo de
la entrada, y fuera de aquí solo circula el nombre del cliente.
"""

import hmac
from collections.abc import Mapping
from typing import Optional

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader

from app.errors import ConfigError

API_KEY_HEADER = "X-API-Key"
ENTRY_SEPARATOR = ","
CLIENT_SEPARATOR = ":"
UNAUTHORIZED_DETAIL = "invalid or missing API key"
RATE_LIMITED_DETAIL = "rate limit exceeded"
UNAUTHORIZED_STATUS = 401
RATE_LIMITED_STATUS = 429
RETRY_AFTER_HEADER = "Retry-After"


class ApiKeys(Mapping):
    """Mapa inmutable de cliente a clave cuyo ``repr`` nunca muestra claves.

    Se compara igual que un ``dict`` con los mismos pares. Si alguien lo
    escribe en un log por error, solo salen los nombres de los clientes.

    :param keys: Clave de cada cliente
    :type keys: dict[str, str] or None
    """

    def __init__(self, keys=None):
        self._keys = dict(keys or {})

    def __getitem__(self, client):
        """Devuelve la clave de ``client``.

        :param client: Nombre del cliente
        :type client: str
        :return: La clave del cliente
        :rtype: str
        :raises KeyError: Si el cliente no existe
        """
        return self._keys[client]

    def __iter__(self):
        """Recorre los nombres de los clientes.

        :return: Iterador de nombres
        :rtype: collections.abc.Iterator
        """
        return iter(self._keys)

    def __len__(self):
        """Cuenta los clientes.

        :return: Número de clientes
        :rtype: int
        """
        return len(self._keys)

    def __bool__(self):
        """Indica si hay al menos un cliente.

        :return: ``True`` si hay clientes
        :rtype: bool
        """
        return bool(self._keys)

    def __repr__(self):
        """Muestra solo los nombres de los clientes, nunca sus claves.

        :return: Representación sin secretos
        :rtype: str
        """
        return f"ApiKeys(clients={sorted(self._keys)!r})"


def _entry_error(position, entry, reason):
    """Arma el error de una entrada de ``API_KEYS`` sin mostrar su valor.

    :param position: Posición de la entrada, desde 1
    :type position: int
    :param entry: Entrada que falla; solo se usa su largo
    :type entry: str
    :param reason: Motivo del error
    :type reason: str
    :return: Error listo para lanzar
    :rtype: app.errors.ConfigError
    """
    return ConfigError(
        f"API_KEYS: la entrada {position} (largo {len(entry)}) {reason}. "
        "La forma es cliente:clave,cliente2:clave2."
    )


def parse_api_keys(raw):
    """Lee ``API_KEYS`` con la forma ``cliente:clave,cliente2:clave2``.

    :param raw: Valor de ``API_KEYS``; vacío no define clientes
    :type raw: str
    :return: Clave de cada cliente
    :rtype: ApiKeys
    :raises app.errors.ConfigError: Si una entrada no tiene ``:``, tiene el
        cliente o la clave vacíos, o repite un cliente o una clave
    """
    if not raw or not raw.strip():
        return ApiKeys()
    keys = {}
    seen_keys = set()
    for position, raw_entry in enumerate(raw.split(ENTRY_SEPARATOR), start=1):
        entry = raw_entry.strip()
        client, separator, key = entry.partition(CLIENT_SEPARATOR)
        client, key = client.strip(), key.strip()
        if not separator:
            raise _entry_error(position, entry, "no tiene ':'")
        if not client:
            raise _entry_error(position, entry, "no tiene cliente")
        if not key:
            raise _entry_error(position, entry, "no tiene clave")
        if client in keys:
            raise _entry_error(position, entry, "repite un cliente")
        if key in seen_keys:
            raise _entry_error(position, entry, "repite una clave")
        keys[client] = key
        seen_keys.add(key)
    return ApiKeys(keys)


class KeyRing:
    """Encuentra el cliente dueño de una clave sin filtrar tiempos.

    :param api_keys: Clave de cada cliente
    :type api_keys: dict[str, str]
    """

    def __init__(self, api_keys):
        self._entries = [
            (client, key.encode("utf-8")) for client, key in api_keys.items()
        ]

    def client_for(self, key):
        """Devuelve el cliente de ``key`` o ``None``.

        Compara contra todas las claves con :func:`hmac.compare_digest`, sin
        cortar al encontrar la primera.

        :param key: Clave recibida en ``X-API-Key``
        :type key: str or None
        :return: Nombre del cliente o ``None`` si la clave no existe
        :rtype: str or None
        """
        if not key:
            return None
        candidate = key.encode("utf-8")
        found = None
        for client, secret in self._entries:
            if hmac.compare_digest(candidate, secret) and found is None:
                found = client
        return found


def build_require_client(keyring, limiter):
    """Crea la dependencia que exige clave y aplica el límite por cliente.

    :param keyring: Claves válidas
    :type keyring: KeyRing
    :param limiter: Límite de peticiones por cliente
    :type limiter: app.ratelimit.RateLimiter
    :return: Dependencia de FastAPI que devuelve el nombre del cliente
    :rtype: callable
    """
    api_key_header = APIKeyHeader(name=API_KEY_HEADER, auto_error=False)

    def require_client(
        request: Request, api_key: Optional[str] = Security(api_key_header)
    ):
        """Valida la clave, aplica el límite y deja el cliente en la petición.

        :param request: Petición en curso
        :type request: fastapi.Request
        :param api_key: Valor de ``X-API-Key``, si vino
        :type api_key: str or None
        :return: Nombre del cliente
        :rtype: str
        :raises fastapi.HTTPException: ``401`` sin clave válida o ``429`` si
            el cliente pasó su límite
        """
        client = keyring.client_for(api_key)
        if client is None:
            raise HTTPException(UNAUTHORIZED_STATUS, detail=UNAUTHORIZED_DETAIL)
        request.state.client = client
        retry_after = limiter.check(client)
        if retry_after is not None:
            raise HTTPException(
                RATE_LIMITED_STATUS,
                detail=RATE_LIMITED_DETAIL,
                headers={RETRY_AFTER_HEADER: str(retry_after)},
            )
        return client

    return require_client
