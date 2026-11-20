"""Claves de acceso por cliente.

``parse_api_keys`` interpreta ``API_KEYS`` (``cliente:clave,cliente2:clave2``)
y ``ApiKeyAuth.client_for`` devuelve el cliente de una clave o ``None``.

Reglas de seguridad de este modulo:

- Una clave se guarda como ``pydantic.SecretStr``: no sale en ``repr``.
- Un error de formato nombra la entrada (contando desde 1) y su largo,
  nunca su valor, y no encadena ninguna otra excepcion.
- Las claves se comparan con ``hmac.compare_digest`` contra todas las
  configuradas, para no revelar por tiempo cual se parece.

:seealso: ``spec/04-production.md`` (punto 1) y ``output/plan.md``.
"""

from __future__ import annotations

import hmac
import re

from pydantic import BaseModel, SecretStr

ENTRY_SEPARATOR = ","
CLIENT_SEPARATOR = ":"
# El cliente va al log: solo caracteres seguros (evita inyeccion en logs).
VALID_CLIENT = re.compile(r"[A-Za-z0-9._-]{1,64}")
# La clave no puede tener espacios ni separadores.
VALID_KEY = re.compile(r"[^\s,]+")
KEY_ENCODING = "utf-8"
MALFORMED = "está mal formada"
REPEATED_KEY = "repite una clave"


class ApiKey(BaseModel, frozen=True):
    """Un cliente y su clave.

    :param client: Nombre del cliente (va al log y a la traza).
    :type client: str
    :param key: Clave secreta del cliente.
    :type key: pydantic.SecretStr
    """

    client: str
    key: SecretStr


def _malformed(index: int, entry: str, reason: str = MALFORMED) -> ValueError:
    """Construye el error de una entrada sin incluir su valor.

    :param index: Posicion de la entrada, contando desde 1.
    :type index: int
    :param entry: Texto de la entrada (solo se usa su largo).
    :type entry: str
    :param reason: Motivo corto del rechazo.
    :type reason: str
    :return: Error con la posicion y el largo de la entrada.
    :rtype: ValueError
    """
    return ValueError(
        f"API_KEYS: la entrada {index} {reason} (largo {len(entry)})"
    )


def _parse_entry(index: int, entry: str) -> ApiKey:
    """Interpreta una entrada ``cliente:clave``.

    :param index: Posicion de la entrada, contando desde 1.
    :type index: int
    :param entry: Texto de la entrada, ya sin espacios en los extremos.
    :type entry: str
    :return: Cliente y clave.
    :rtype: ApiKey
    :raises ValueError: Si falta ``:``, el cliente o la clave, o si
        alguno tiene caracteres no permitidos.
    """
    client, separator, key = entry.partition(CLIENT_SEPARATOR)
    client, key = client.strip(), key.strip()
    valid = (
        separator
        and VALID_CLIENT.fullmatch(client)
        and VALID_KEY.fullmatch(key)
    )
    if not valid:
        raise _malformed(index, entry)
    return ApiKey(client=client, key=SecretStr(key))


def parse_api_keys(raw: str | None) -> tuple[ApiKey, ...]:
    """Interpreta ``API_KEYS``.

    Un texto vacio da una tupla vacia. Los espacios alrededor de cada
    entrada, del cliente y de la clave se ignoran.

    :param raw: Valor de ``API_KEYS``.
    :type raw: str | None
    :return: Clientes y claves en el orden recibido.
    :rtype: tuple[ApiKey, ...]
    :raises ValueError: Si una entrada esta mal formada o repite una
        clave; el mensaje trae la posicion y el largo, nunca el valor.
    """
    text = (raw or "").strip()
    if not text:
        return ()
    parsed: list[ApiKey] = []
    seen: set[str] = set()
    for index, entry in enumerate(text.split(ENTRY_SEPARATOR), start=1):
        api_key = _parse_entry(index, entry.strip())
        secret = api_key.key.get_secret_value()
        if secret in seen:
            raise _malformed(index, entry.strip(), REPEATED_KEY)
        seen.add(secret)
        parsed.append(api_key)
    return tuple(parsed)


class ApiKeyAuth:
    """Busca el cliente de una clave.

    :param keys: Clientes y claves validos.
    :type keys: tuple[ApiKey, ...]
    """

    def __init__(self, keys: tuple[ApiKey, ...] | list[ApiKey]) -> None:
        """Guarda las claves como bytes, listas para comparar.

        :param keys: Clientes y claves validos.
        :type keys: tuple[ApiKey, ...] | list[ApiKey]
        """
        self._keys = tuple(
            (item.client, item.key.get_secret_value().encode(KEY_ENCODING))
            for item in keys
        )

    def client_for(self, key: str | None) -> str | None:
        """Devuelve el cliente de ``key`` o ``None``.

        Compara con ``hmac.compare_digest`` contra todas las claves, sin
        cortar al encontrar una, para que el tiempo no dependa de cual
        coincide.

        :param key: Valor del encabezado ``X-API-Key``.
        :type key: str | None
        :return: Nombre del cliente o ``None`` si falta o no coincide.
        :rtype: str | None
        """
        if not key:
            return None
        candidate = key.encode(KEY_ENCODING)
        found = None
        for client, expected in self._keys:
            if hmac.compare_digest(candidate, expected) and found is None:
                found = client
        return found
