"""Prueba de humo del HR Assistant publicado (spec/04-production.md, punto 8).

Uso: ``SMOKE_API_KEY=<clave> python scripts/smoke.py https://<servicio>.onrender.com``

La clave se lee solo de la variable ``SMOKE_API_KEY``, nunca de un argumento,
para que no quede en el historial de la terminal. La clave nunca se imprime.
Comprueba tres cosas e imprime ``[OK]`` o ``[FAIL]`` en cada una:

- ``GET /health`` responde ``200``.
- ``POST /ask`` sin clave responde ``401``.
- ``POST /ask`` con clave responde ``200``.
"""

import os
import sys
import time

import httpx

KEY_VARIABLE = "SMOKE_API_KEY"
API_KEY_HEADER = "X-API-Key"
QUESTION = {"question": "¿Quién es EMP-0004?"}
# Render free duerme el servicio; despertarlo puede tardar cerca de un minuto
REQUEST_TIMEOUT_SECONDS = 90
HEALTH_ATTEMPTS = 5
HEALTH_WAIT_SECONDS = 10
EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2


def wait_for_health(client, url, attempts=HEALTH_ATTEMPTS, wait=HEALTH_WAIT_SECONDS):
    """Pide ``/health`` hasta que responda ``200`` o se acaben los intentos.

    :param client: Cliente HTTP
    :type client: httpx.Client
    :param url: URL base del servicio, sin ``/`` al final
    :type url: str
    :param attempts: Intentos máximos
    :type attempts: int
    :param wait: Segundos de espera entre intentos
    :type wait: float
    :return: Código del último intento; ``0`` si nunca hubo respuesta
    :rtype: int
    """
    status = 0
    for attempt in range(attempts):
        try:
            status = client.get(f"{url}/health").status_code
        except httpx.TransportError:
            status = 0
        if status == 200:
            return status
        if attempt < attempts - 1:
            time.sleep(wait)
    return status


def _ask_status(client, url, headers):
    """Manda la pregunta de prueba a ``/ask`` y devuelve el código.

    :param client: Cliente HTTP
    :type client: httpx.Client
    :param url: URL base del servicio
    :type url: str
    :param headers: Encabezados de la petición
    :type headers: dict[str, str]
    :return: Código HTTP; ``0`` si no hubo respuesta
    :rtype: int
    """
    try:
        return client.post(f"{url}/ask", json=QUESTION, headers=headers).status_code
    except httpx.TransportError:
        return 0


def run_checks(client, url, key, wait=HEALTH_WAIT_SECONDS):
    """Corre las tres comprobaciones e imprime ``[OK]`` o ``[FAIL]`` en cada una.

    :param client: Cliente HTTP
    :type client: httpx.Client
    :param url: URL base del servicio
    :type url: str
    :param key: Clave del cliente; nunca se imprime
    :type key: str
    :param wait: Segundos de espera entre intentos de ``/health``
    :type wait: float
    :return: ``True`` si las tres pasan
    :rtype: bool
    """
    base = url.rstrip("/")
    checks = [
        ("GET /health", 200, wait_for_health(client, base, wait=wait)),
        ("POST /ask sin clave", 401, _ask_status(client, base, {})),
        ("POST /ask con clave", 200, _ask_status(client, base, {API_KEY_HEADER: key})),
    ]
    for name, expected, status in checks:
        label = "OK" if status == expected else "FAIL"
        print(f"[{label}] {name} -> {status} (esperado {expected})")
    return all(status == expected for _, expected, status in checks)


def main(args, environ=None, client=None):
    """Lee la URL y la clave, corre la prueba y devuelve el código de salida.

    :param args: Argumentos de la línea de comandos, sin el nombre del script
    :type args: list[str]
    :param environ: Variables de entorno; por omisión ``os.environ``
    :type environ: Mapping[str, str] or None
    :param client: Cliente HTTP inyectado (para pruebas); por omisión uno nuevo
    :type client: httpx.Client or None
    :return: ``0`` si todo pasa, ``1`` si algo falla, ``2`` si el uso es incorrecto
    :rtype: int
    """
    environ = os.environ if environ is None else environ
    key = environ.get(KEY_VARIABLE, "").strip()
    if len(args) != 1 or not key:
        print(f"Uso: {KEY_VARIABLE}=<clave> python scripts/smoke.py <url>")
        return EXIT_USAGE
    if client is not None:
        passed = run_checks(client, args[0], key)
    else:
        with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as own_client:
            passed = run_checks(own_client, args[0], key)
    return EXIT_OK if passed else EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
