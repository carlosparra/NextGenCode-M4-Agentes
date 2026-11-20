"""Prueba de humo contra el HR Assistant publicado (spec/04-production.md, punto 8).

Uso: ``SMOKE_API_KEY=<clave> python scripts/smoke.py https://<servicio>.onrender.com``

La clave se lee solo de la variable ``SMOKE_API_KEY``: nunca de un argumento,
porque quedaría en el historial de la terminal. Nunca se imprime.
"""

import os
import sys

import httpx

KEY_VARIABLE = "SMOKE_API_KEY"
QUESTION = {"question": "¿Quién es EMP-0004?"}
# Render despierta un servicio dormido en hasta un minuto
TIMEOUT_SECONDS = 90
USAGE = f"Uso: {KEY_VARIABLE}=<clave> python scripts/smoke.py <url>"


def _status(send) -> int | None:
    """Hace una petición y devuelve su código, o ``None`` si no hubo respuesta.

    :param send: Función sin argumentos que hace la petición
    :type send: collections.abc.Callable[[], httpx.Response]
    :return: Código HTTP, o ``None`` si falló la conexión
    :rtype: int | None
    """
    try:
        return send().status_code
    except httpx.HTTPError as exc:
        # Solo el tipo de error: el mensaje podría incluir encabezados
        print(f"    sin respuesta: {type(exc).__name__}")
        return None


def run_checks(url: str, key: str, client: httpx.Client) -> bool:
    """Corre las tres comprobaciones e imprime ``[OK]`` o ``[FAIL]`` en cada una.

    :param url: URL base del servicio, sin barra final
    :type url: str
    :param key: Clave válida para ``X-API-Key``
    :type key: str
    :param client: Cliente HTTP
    :type client: httpx.Client
    :return: ``True`` si las tres pasan
    :rtype: bool
    """
    checks = [
        ("GET /health", 200, lambda: client.get(f"{url}/health")),
        ("POST /ask sin clave", 401, lambda: client.post(f"{url}/ask", json=QUESTION)),
        ("POST /ask con clave", 200, lambda: client.post(
            f"{url}/ask", json=QUESTION, headers={"X-API-Key": key}
        )),
    ]
    passed = True
    for name, expected, send in checks:
        received = _status(send)
        ok = received == expected
        passed = passed and ok
        label = "OK" if ok else "FAIL"
        print(f"[{label}] {name} -> {received} (esperado {expected})")
    return passed


def main(args: list[str]) -> int:
    """Corre la prueba de humo; 0 si todo pasa, 1 si algo falla, 2 si falta algo.

    :param args: Argumentos de la línea de comandos, sin el nombre del script
    :type args: list[str]
    :return: Código de salida
    :rtype: int
    """
    key = os.environ.get(KEY_VARIABLE, "")
    if len(args) != 1 or not key:
        print(USAGE)
        return 2
    with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
        passed = run_checks(args[0].rstrip("/"), key, client)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
