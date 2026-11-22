"""Prueba de humo contra el producto publicado.

Uso: ``uv run python -m verification production https://<servicio>.onrender.com``

La clave se lee de la variable ``SMOKE_API_KEY``: nunca va en el comando ni en
el chat, porque quedaría en el historial.
"""

import os
import sys

import httpx


EMPLOYEE_NAME = "Jorge Díaz"
FAILURE_PREFIX = "No pude completar"
# Datos personales inventados: no pertenecen a nadie, solo tienen la forma
FAKE_CURP = "AAAA010101HDFBBB09"
FAKE_EMAIL = "persona.prueba@example.com"
# Texto que identifica la pregunta con datos personales (lo usan las pruebas)
PII_MARKER = FAKE_CURP
# Rutas que la documentación pública debe describir
DOCUMENTED_PATHS = {"/ask", "/health"}
PII_QUESTION = f"Mi CURP es {FAKE_CURP} y mi correo es {FAKE_EMAIL}. ¿Quién soy?"


def masks_personal_data(response: httpx.Response) -> bool:
    """Indica si la respuesta a la pregunta con datos personales no los repite.

    :param response: Respuesta de ``POST /ask`` con clave
    :type response: httpx.Response
    :return: ``True`` si es 200 y el cuerpo no trae la CURP ni el correo
        inventados, escritos de cualquier forma de mayúsculas
    :rtype: bool
    """
    if response.status_code != 200:
        return False
    body = response.text.lower()
    return FAKE_CURP.lower() not in body and FAKE_EMAIL.lower() not in body


def has_employee(response: httpx.Response) -> bool:
    """Indica si la respuesta de ``/ask`` trae al empleado preguntado.

    El código 200 no basta: el agente devuelve 200 también cuando no logra
    contestar y responde un mensaje fijo de fallo.

    :param response: Respuesta de ``POST /ask`` con clave
    :type response: httpx.Response
    :return: ``True`` si es 200, el campo ``answer`` nombra al empleado y no es
        el mensaje de fallo
    :rtype: bool
    """
    if response.status_code != 200:
        return False
    try:
        answer = response.json()["answer"]
    except (ValueError, KeyError, TypeError):
        return False
    return (
        isinstance(answer, str)
        and EMPLOYEE_NAME in answer
        and FAILURE_PREFIX not in answer
    )


def documents_api(response: httpx.Response) -> bool:
    """Indica si ``/openapi.json`` es público y describe las rutas principales.

    :param response: Respuesta de ``GET /openapi.json`` sin clave
    :type response: httpx.Response
    :return: ``True`` si es 200 y el esquema trae ``/ask`` y ``/health``
    :rtype: bool
    """
    if response.status_code != 200:
        return False
    try:
        paths = response.json()["paths"]
    except (ValueError, KeyError, TypeError):
        return False
    return isinstance(paths, dict) and DOCUMENTED_PATHS <= set(paths)


def _show(name: str, passed: bool, detail: str) -> bool:
    """Imprime una línea ``[OK]`` o ``[FAIL]`` y devuelve el resultado.

    :param name: Nombre de la comprobación
    :type name: str
    :param passed: Si la comprobación pasó
    :type passed: bool
    :param detail: Texto que sigue al nombre
    :type detail: str
    :return: El mismo ``passed``
    :rtype: bool
    """
    print(f"  [{'OK' if passed else 'FAIL'}] {name} -> {detail}")
    return passed


def _show_status(name: str, expected: int, response: httpx.Response) -> bool:
    """Compara el código de estado con el esperado y lo imprime.

    :param name: Nombre de la comprobación
    :type name: str
    :param expected: Código esperado
    :type expected: int
    :param response: Respuesta recibida
    :type response: httpx.Response
    :return: ``True`` si el código es el esperado
    :rtype: bool
    """
    return _show(
        name, response.status_code == expected,
        f"{response.status_code} (esperado {expected})",
    )


def smoke(url: str, key: str, client: httpx.Client) -> bool:
    """Corre las seis comprobaciones de la prueba de humo contra el servicio.

    Imprime el código recibido en cada una: con él se ve la causa de una falla
    (401: la clave no coincide; 502: el modelo no responde). Una línea dice si
    la documentación pública describe la API, otra si la respuesta con clave
    trae al empleado y la última, si una pregunta con una CURP y un correo
    inventados no los recibe de vuelta. Nunca imprime la respuesta ni los
    datos inventados.

    :param url: Dirección base del servicio, sin barra final
    :type url: str
    :param key: Clave de cliente para ``X-API-Key``
    :type key: str
    :param client: Cliente HTTP con el tiempo máximo ya definido
    :type client: httpx.Client
    :return: ``True`` si los tres códigos de estado son los esperados, la
        documentación describe la API, la respuesta con clave trae al empleado
        y la respuesta a la pregunta con datos personales no los repite
    :rtype: bool
    """
    question = {"question": "¿Quién es EMP-0004?"}
    headers = {"X-API-Key": key}
    results = [
        _show_status("GET /health", 200, client.get(f"{url}/health")),
        _show("GET /openapi.json", documents_api(client.get(f"{url}/openapi.json")),
              "la documentación describe /ask y /health"),
        _show_status(
            "POST /ask sin clave", 401, client.post(f"{url}/ask", json=question)
        ),
    ]
    asked = client.post(f"{url}/ask", json=question, headers=headers)
    results += [
        _show_status("POST /ask con clave", 200, asked),
        _show("POST /ask con clave", has_employee(asked),
              "la respuesta trae al empleado"),
    ]
    personal = client.post(
        f"{url}/ask", json={"question": PII_QUESTION}, headers=headers
    )
    results.append(_show(
        "POST /ask con datos personales", masks_personal_data(personal),
        "la respuesta no los trae",
    ))
    return all(results)


def main(args: list[str]) -> int:
    """Corre la prueba de humo contra el servicio publicado.

    :param args: Argumentos de la línea de comandos; debe traer un solo elemento,
        la URL del servicio
    :type args: list[str]
    :return: 0 si todo pasa, 1 si alguna comprobación falla y 2 si falta la URL o
        la variable ``SMOKE_API_KEY``
    :rtype: int
    """
    key = os.environ.get("SMOKE_API_KEY", "")
    if len(args) != 1 or not key:
        print("Uso: SMOKE_API_KEY=<clave> python -m verification production <url>")
        return 2
    # Render despierta el servicio dormido en hasta un minuto
    with httpx.Client(timeout=90) as client:
        passed = smoke(args[0].rstrip("/"), key, client)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
