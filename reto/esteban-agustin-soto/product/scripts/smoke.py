"""Prueba de humo contra el producto publicado.

Uso: ``SMOKE_API_KEY=<clave> python scripts/smoke.py <url>``

La clave se lee de la variable ``SMOKE_API_KEY``, nunca de un argumento, para
que no quede en el historial del terminal.
"""

import os
import sys

import httpx

QUESTION = {"question": "¿Quién es EMP-0004?"}


def check(name: str, expected: int, response: httpx.Response) -> bool:
    """Imprime [OK] o [FAIL] para una comprobación y devuelve si pasó.

    :param name: Nombre de la comprobación, para el mensaje
    :type name: str
    :param expected: Código HTTP esperado
    :type expected: int
    :param response: Respuesta recibida del servicio
    :type response: httpx.Response
    :return: True si el código coincide con el esperado
    :rtype: bool
    """
    passed = response.status_code == expected
    label = "OK" if passed else "FAIL"
    print(f"[{label}] {name}: {response.status_code} (esperado {expected})")
    return passed


def smoke(url: str, key: str, client: httpx.Client) -> bool:
    """Comprueba /health, /ask sin clave y /ask con clave.

    :param url: URL base del servicio, sin barra final
    :type url: str
    :param key: Clave de API para la llamada autenticada
    :type key: str
    :param client: Cliente HTTP con el que se hacen las llamadas
    :type client: httpx.Client
    :return: True si las tres comprobaciones pasan
    :rtype: bool
    """
    results = [
        check("GET /health", 200, client.get(f"{url}/health")),
        check("POST /ask sin clave", 401, client.post(f"{url}/ask", json=QUESTION)),
        check(
            "POST /ask con clave",
            200,
            client.post(f"{url}/ask", json=QUESTION, headers={"X-API-Key": key}),
        ),
    ]
    return all(results)


def main(args: list[str]) -> int:
    """Corre la prueba de humo; 0 si todo pasa, 2 si faltan datos.

    :param args: Argumentos de la línea de comandos, sin el nombre del script
        (se espera solo la URL)
    :type args: list[str]
    :return: Código de salida: 0 si todo pasa, 1 si alguna comprobación
        falla, 2 si faltan la URL o ``SMOKE_API_KEY``
    :rtype: int
    """
    key = os.environ.get("SMOKE_API_KEY", "")
    if len(args) != 1 or not key:
        print("Uso: SMOKE_API_KEY=<clave> python scripts/smoke.py <url>")
        return 2
    # Render despierta un servicio dormido en hasta un minuto
    with httpx.Client(timeout=90) as client:
        return 0 if smoke(args[0].rstrip("/"), key, client) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
