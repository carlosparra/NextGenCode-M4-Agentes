"""Prueba de humo contra el producto publicado.

Uso: ``SMOKE_API_KEY=<clave> python scripts/smoke.py https://<servicio>.onrender.com``

La clave se lee solo de la variable ``SMOKE_API_KEY``, nunca de un argumento,
para que no quede en el historial de la terminal. Comprueba tres cosas e imprime
``[OK]`` o ``[FAIL]`` en cada una; termina con 0 solo si las tres pasan.
"""

import os
import sys
from collections.abc import Callable, Mapping, Sequence

import httpx

KEY_VARIABLE = "SMOKE_API_KEY"
QUESTION = {"question": "¿Quién es EMP-0004?"}
# Render despierta un servicio dormido en hasta un minuto.
TIMEOUT_SECONDS = 90
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2


def status_of(send: Callable[[], httpx.Response]) -> int | None:
    """Hace una petición y devuelve su código, o ``None`` si no hubo respuesta.

    :param send: Función sin argumentos que hace la petición
    :type send: collections.abc.Callable
    :return: Código HTTP recibido; ``None`` si falló la conexión
    :rtype: int or None
    """
    try:
        return send().status_code
    except httpx.HTTPError as error:
        # Solo el tipo del error: el mensaje podría traer datos de la petición.
        print(f"  sin respuesta: {type(error).__name__}", file=sys.stderr)
        return None


def run_checks(url: str, key: str, client: httpx.Client) -> list[tuple]:
    """Hace las tres peticiones de la prueba de humo.

    :param url: URL base del servicio, sin ``/`` final
    :type url: str
    :param key: Clave válida para ``X-API-Key``
    :type key: str
    :param client: Cliente HTTP que hace las peticiones
    :type client: httpx.Client
    :return: Por cada chequeo, su nombre, el código esperado y el recibido
    :rtype: list[tuple[str, int, int | None]]
    """
    ask_url = f"{url}/ask"
    return [
        ("GET /health", 200, status_of(lambda: client.get(f"{url}/health"))),
        (
            "POST /ask sin clave",
            401,
            status_of(lambda: client.post(ask_url, json=QUESTION)),
        ),
        (
            "POST /ask con clave",
            200,
            status_of(
                lambda: client.post(
                    ask_url, json=QUESTION, headers={"X-API-Key": key}
                )
            ),
        ),
    ]


def report(checks: list[tuple]) -> bool:
    """Imprime ``[OK]`` o ``[FAIL]`` por chequeo, sin mostrar nunca la clave.

    :param checks: Nombre, código esperado y código recibido de cada chequeo
    :type checks: list[tuple[str, int, int | None]]
    :return: ``True`` si todos pasaron
    :rtype: bool
    """
    for name, expected, received in checks:
        status = "OK" if received == expected else "FAIL"
        print(f"[{status}] {name} -> {received} (esperado {expected})")
    return all(received == expected for _, expected, received in checks)


def main(
    argv: Sequence[str],
    environ: Mapping[str, str],
    http_client: httpx.Client | None = None,
) -> int:
    """Corre la prueba de humo.

    :param argv: Argumentos sin el nombre del programa; solo la URL
    :type argv: collections.abc.Sequence[str]
    :param environ: Variables de entorno; de ahí sale ``SMOKE_API_KEY``
    :type environ: collections.abc.Mapping[str, str]
    :param http_client: Cliente HTTP inyectable; si falta se crea uno
    :type http_client: httpx.Client or None
    :return: 0 si todo pasa, 1 si algo falla, 2 si el uso es incorrecto
    :rtype: int
    """
    key = environ.get(KEY_VARIABLE, "").strip()
    if len(argv) != 1 or not key:
        print(
            f"Uso: {KEY_VARIABLE}=<clave> python scripts/smoke.py <url>",
            file=sys.stderr,
        )
        return EXIT_USAGE
    url = argv[0].rstrip("/")
    if http_client is not None:
        return EXIT_OK if report(run_checks(url, key, http_client)) else EXIT_FAILED
    with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
        return EXIT_OK if report(run_checks(url, key, client)) else EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], os.environ))
