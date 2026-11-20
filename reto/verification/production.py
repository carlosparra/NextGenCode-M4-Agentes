"""Prueba de humo contra el producto publicado.

Uso: ``uv run python -m verification production https://<servicio>.onrender.com``

La clave se lee de la variable ``SMOKE_API_KEY``: nunca va en el comando ni en
el chat, porque quedaría en el historial.
"""

import os
import re
import sys

import httpx

QUESTION = {"question": "¿Quién es EMP-0004?"}
# El directorio no tiene teléfonos: el modelo real no debe inventar uno.
PHONE_QUESTION = {"question": "¿Cuál es el número de teléfono de EMP-0001?"}
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
PHONE_LIKE = re.compile(r"\d(?:[ .()-]?\d){6,}")


def shows_a_phone(response: httpx.Response) -> bool:
    """``True`` si la respuesta trae algo con forma de teléfono (7 o más dígitos).

    Las fechas ``AAAA-MM-DD`` (fecha de ingreso) no cuentan.
    """
    try:
        answer = str(response.json().get("answer", ""))
    except ValueError:
        return False
    return bool(PHONE_LIKE.search(ISO_DATE.sub("", answer)))


def smoke(url: str, key: str, client: httpx.Client) -> bool:
    """Comprueba ``/health``, ``/docs``, ``/ask`` sin y con clave, y que no invente datos.

    Imprime el código recibido en cada una: con él se ve la causa de una falla
    (401: la clave no coincide; 502: el modelo no responde).
    """
    headers = {"X-API-Key": key}
    checks = [
        ("GET /health", 200, client.get(f"{url}/health")),
        ("GET /docs", 200, client.get(f"{url}/docs")),
        ("POST /ask sin clave", 401, client.post(f"{url}/ask", json=QUESTION)),
        ("POST /ask con clave", 200, client.post(
            f"{url}/ask", json=QUESTION, headers=headers
        )),
    ]
    passed = True
    for name, expected, response in checks:
        ok = response.status_code == expected
        passed = passed and ok
        print(f"  [{'OK' if ok else 'FAIL'}] {name} -> {response.status_code} "
              f"(esperado {expected})")
    phone = client.post(f"{url}/ask", json=PHONE_QUESTION, headers=headers)
    invented = phone.status_code != 200 or shows_a_phone(phone)
    passed = passed and not invented
    detail = "inventa o muestra un teléfono" if invented else "no inventa datos"
    print(f"  [{'FAIL' if invented else 'OK'}] POST /ask teléfono -> "
          f"{phone.status_code} ({detail})")
    return passed


def main(args: list[str]) -> int:
    """Corre la prueba de humo; 0 si todo pasa."""
    key = os.environ.get("SMOKE_API_KEY", "")
    if len(args) != 1 or not key:
        print(
            "Uso (Mac/Linux): SMOKE_API_KEY=<clave> "
            "python -m verification production <url>"
            "Uso (PowerShell): $env:SMOKE_API_KEY = '<clave>' y luego "
            "uv run python -m verification production <url>"
        )
        return 2
    # Render despierta el servicio dormido en hasta un minuto
    with httpx.Client(timeout=90) as client:
        passed = smoke(args[0].rstrip("/"), key, client)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
