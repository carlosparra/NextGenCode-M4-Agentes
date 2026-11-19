"""Prueba de humo contra el HR Assistant publicado.

Uso: ``SMOKE_API_KEY=<clave> python scripts/smoke.py https://<servicio>.onrender.com``

La clave se lee de la variable ``SMOKE_API_KEY``, nunca de un argumento, para que
no quede en el historial de la terminal. Comprueba tres cosas e imprime ``[OK]``
o ``[FAIL]`` en cada una:

- ``GET /health`` responde 200.
- ``POST /ask`` sin clave responde 401.
- ``POST /ask`` con clave responde 200.
"""

import os
import sys

import httpx

KEY_VARIABLE = "SMOKE_API_KEY"
QUESTION = {"question": "¿Quién es EMP-0004?"}
# Render despierta un servicio dormido en hasta un minuto.
TIMEOUT_SECONDS = 90
USAGE_EXIT_CODE = 2


def run_checks(url: str, key: str, client: httpx.Client) -> bool:
    """Corre las tres comprobaciones e imprime el resultado de cada una.

    :param url: URL base del servicio, sin barra final
    :type url: str
    :param key: Clave de API del cliente de prueba
    :type key: str
    :param client: Cliente HTTP a usar
    :type client: httpx.Client
    :return: ``True`` si las tres pasan
    :rtype: bool
    """
    checks = [
        ("GET /health", 200, lambda: client.get(f"{url}/health")),
        ("POST /ask sin clave", 401, lambda: client.post(f"{url}/ask", json=QUESTION)),
        (
            "POST /ask con clave",
            200,
            lambda: client.post(
                f"{url}/ask", json=QUESTION, headers={"X-API-Key": key}
            ),
        ),
    ]
    passed = True
    for name, expected, request in checks:
        try:
            status = request().status_code
        except httpx.HTTPError as error:
            # Se muestra el tipo de error, nunca la clave.
            print(f"  [FAIL] {name} -> {type(error).__name__}")
            passed = False
            continue
        label = "OK" if status == expected else "FAIL"
        print(f"  [{label}] {name} -> {status} (esperado {expected})")
        passed = passed and status == expected
    return passed


def main(args: list[str], transport: httpx.BaseTransport | None = None) -> int:
    """Lee la URL y la clave y corre la prueba de humo.

    :param args: Argumentos de la línea de comandos, sin el nombre del programa
    :type args: list[str]
    :param transport: Transporte HTTP opcional; las pruebas pasan uno sin red
    :type transport: httpx.BaseTransport | None
    :return: 0 si todo pasa, 1 si algo falla, 2 si el uso es incorrecto
    :rtype: int
    """
    key = os.environ.get(KEY_VARIABLE, "")
    # Sin clave se sale antes de crear el cliente: no se toca la red.
    if len(args) != 1 or not key:
        print(f"Uso: {KEY_VARIABLE}=<clave> python scripts/smoke.py <url>")
        return USAGE_EXIT_CODE
    with httpx.Client(timeout=TIMEOUT_SECONDS, transport=transport) as client:
        passed = run_checks(args[0].rstrip("/"), key, client)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
