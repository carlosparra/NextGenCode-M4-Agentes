"""Prueba de humo contra el sistema publicado (o local).

Uso::

    export SMOKE_API_KEY='<clave con permiso ask>'   # nunca como argumento
    export SMOKE_MCP_KEY='<clave con permiso mcp>'       # opcional
    export SMOKE_METRICS_KEY='<clave con permiso metrics>'  # opcional
    python scripts/smoke.py https://hr-assistant-ebersilva.onrender.com

Sin las claves opcionales se usa ``SMOKE_API_KEY`` para todo.

Comprueba salud, autenticación, una pregunta real, una herramienta MCP por
HTTP y las métricas. Imprime ``[OK]`` o ``[FAIL]`` con el código recibido.
"""

from __future__ import annotations

import os
import sys

import httpx

MCP_HEADERS = {"Accept": "application/json, text/event-stream"}
MCP_CALL = {
    "jsonrpc": "2.0",
    "id": "smoke",
    "method": "tools/call",
    "params": {"name": "department_summary", "arguments": {"department": "Ventas"}},
}


def checks(  # pylint: disable=too-many-locals
    url: str, keys: dict, client: httpx.Client
) -> list[tuple[str, bool, str]]:
    """Corre cada comprobación.

    :param keys: Claves ``ask``, ``mcp`` y ``metrics``
    :type keys: dict
    :return: Nombre, si pasó y el detalle
    :rtype: list[tuple[str, bool, str]]
    """
    auth = {"X-API-Key": keys["ask"]}
    question = {"question": "¿Cuántas vacaciones le quedan a EMP-0004?"}
    results = []
    health = client.get(f"{url}/health")
    results.append(("GET /health", health.status_code == 200, str(health.status_code)))
    anonymous = client.post(f"{url}/ask", json=question)
    results.append(
        (
            "POST /ask sin clave -> 401",
            anonymous.status_code == 401,
            str(anonymous.status_code),
        )
    )
    answer = client.post(f"{url}/ask", json=question, headers=auth)
    detail = str(answer.status_code)
    if answer.status_code == 200:
        body = answer.json()
        detail += f" {body['tools_used']} {body['model']} ${body['cost_usd']:.6f}"
    results.append(("POST /ask con clave", answer.status_code == 200, detail))
    mcp = client.post(
        f"{url}/mcp", json=MCP_CALL, headers={"X-API-Key": keys["mcp"], **MCP_HEADERS}
    )
    ok = mcp.status_code == 200 and not mcp.json().get("result", {}).get("isError")
    results.append(("MCP tools/call department_summary", ok, str(mcp.status_code)))
    metrics = client.get(f"{url}/metrics", headers={"X-API-Key": keys["metrics"]})
    results.append(
        ("GET /metrics", metrics.status_code == 200, str(metrics.status_code))
    )
    if keys["metrics"] != keys["ask"]:
        denied = client.get(f"{url}/metrics", headers=auth)
        results.append(
            (
                "Mínimo privilegio: clave ask en /metrics -> 403",
                denied.status_code == 403,
                str(denied.status_code),
            )
        )
    return results


def main(args: list[str]) -> int:
    """Corre la prueba de humo; 0 si todo pasa."""
    key = os.environ.get("SMOKE_API_KEY", "")
    keys = {
        "ask": key,
        "mcp": os.environ.get("SMOKE_MCP_KEY") or key,
        "metrics": os.environ.get("SMOKE_METRICS_KEY") or key,
    }
    if len(args) != 1 or not key:
        print("Uso: SMOKE_API_KEY=<clave> python scripts/smoke.py <url>")
        return 2
    # Render despierta un servicio gratuito dormido en hasta un minuto
    with httpx.Client(timeout=90) as client:
        results = checks(args[0].rstrip("/"), keys, client)
    for name, ok, detail in results:
        print(f"  [{'OK' if ok else 'FAIL'}] {name} -> {detail}")
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
