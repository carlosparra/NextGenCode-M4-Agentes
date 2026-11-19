"""Claves por cliente (ADR 0011).

``API_KEYS`` tiene la forma ``cliente:clave,cliente2:clave2``. Cada peticion
protegida trae su clave en ``X-API-Key`` y se identifica solo por el nombre del
cliente: la clave nunca se escribe en el log, la traza ni un mensaje de error.
"""

import hmac
import re
from typing import NamedTuple

from app.errors import ConfigError

API_KEYS_VARIABLE = "API_KEYS"
ENTRY_SEPARATOR = ","
PAIR_SEPARATOR = ":"
# El nombre se restringe para que no pueda ser una clave mal partida ni
# inyectar saltos de linea en el log.
CLIENT_NAME_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,64}")
KEY_ENCODING = "utf-8"
# Los surrogates sueltos de un encabezado se codifican sin lanzar excepcion.
KEY_ENCODING_ERRORS = "surrogatepass"
HIDDEN = "***"


class ApiKey(NamedTuple):
    """Cliente y su clave; el ``repr`` oculta la clave.

    :param client: Nombre del cliente
    :type client: str
    :param key: Clave secreta del cliente
    :type key: str
    """

    client: str
    key: str

    def __repr__(self) -> str:
        """Representa la entrada sin mostrar la clave.

        :return: ``ApiKey(client='...', key='***')``
        :rtype: str
        """
        return f"ApiKey(client={self.client!r}, key={HIDDEN!r})"


def _entry_error(position: int, entry: str, reason: str) -> ConfigError:
    """Construye el error de una entrada con su posicion y su largo.

    :param position: Posicion de la entrada, desde 1
    :type position: int
    :param entry: Texto de la entrada (solo se usa su largo)
    :type entry: str
    :param reason: Que esta mal, sin valores
    :type reason: str
    :return: El error listo para lanzar
    :rtype: app.errors.ConfigError
    """
    return ConfigError(
        f"{API_KEYS_VARIABLE} entry {position} (length {len(entry)}): {reason}"
    )


def _parse_entry(position: int, entry: str) -> ApiKey:
    """Valida una entrada ``cliente:clave``.

    :param position: Posicion de la entrada, desde 1
    :type position: int
    :param entry: Entrada sin espacios a los lados
    :type entry: str
    :return: El cliente y su clave
    :rtype: ApiKey
    :raises app.errors.ConfigError: Si la entrada no tiene la forma
        ``cliente:clave``
    """
    if not entry:
        raise _entry_error(position, entry, "must not be empty")
    if PAIR_SEPARATOR not in entry:
        raise _entry_error(position, entry, "must have the form client:key")
    client, key = (part.strip() for part in entry.split(PAIR_SEPARATOR, 1))
    if not CLIENT_NAME_PATTERN.fullmatch(client):
        raise _entry_error(
            position,
            entry,
            "client name must be 1 to 64 letters, digits, '.', '_' or '-'",
        )
    if not key:
        raise _entry_error(position, entry, "key must not be empty")
    return ApiKey(client, key)


def parse_api_keys(raw) -> tuple:
    """Lee ``API_KEYS`` y valida cada entrada.

    La clave se parte en el primer ``:``: una clave puede contener ``:``.
    Una cadena vacia significa que no hay clientes.

    :param raw: Valor de ``API_KEYS`` o ``None``
    :type raw: str or None
    :return: Las entradas en orden
    :rtype: tuple[ApiKey, ...]
    :raises app.errors.ConfigError: Si alguna entrada esta mal formada o se
        repite un cliente o una clave; el mensaje dice la posicion y el largo
        de la entrada, nunca su valor
    """
    text = str(raw or "").strip()
    if not text:
        return ()
    entries = []
    for position, raw_entry in enumerate(text.split(ENTRY_SEPARATOR), start=1):
        entry = raw_entry.strip()
        parsed = _parse_entry(position, entry)
        if any(parsed.client == seen.client for seen in entries):
            raise _entry_error(position, entry, "repeats a client name")
        if any(parsed.key == seen.key for seen in entries):
            raise _entry_error(position, entry, "repeats the key of another entry")
        entries.append(parsed)
    return tuple(entries)


def _as_bytes(text: str) -> bytes:
    """Convierte un texto a bytes para compararlo en tiempo constante.

    :param text: Clave o encabezado
    :type text: str
    :return: El texto en UTF-8
    :rtype: bytes
    """
    return text.encode(KEY_ENCODING, KEY_ENCODING_ERRORS)


class ApiKeyAuthenticator:
    """Identifica al cliente por la clave de ``X-API-Key``.

    Compara con ``hmac.compare_digest`` y recorre todas las claves aunque ya
    haya encontrado una, para no revelar por tiempo cual cliente coincide.

    :param api_keys: Clientes y claves validados
    :type api_keys: tuple[ApiKey, ...]
    """

    def __init__(self, api_keys):
        self._keys = tuple((entry.client, _as_bytes(entry.key)) for entry in api_keys)

    def authenticate(self, header):
        """Devuelve el cliente dueno de la clave o ``None``.

        :param header: Valor de ``X-API-Key`` o ``None``
        :type header: str or None
        :return: El nombre del cliente, o ``None`` si falta o no coincide
        :rtype: str or None
        """
        if not header:
            return None
        candidate = _as_bytes(header)
        matched = None
        for client, key in self._keys:
            if hmac.compare_digest(candidate, key) and matched is None:
                matched = client
        return matched
