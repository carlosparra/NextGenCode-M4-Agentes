"""Prueba de humo contra el servicio publicado.

Uso::

    SMOKE_API_KEY=... SMOKE_MCP_KEY=... SMOKE_METRICS_KEY=... \
        python scripts/smoke.py https://<servicio>.onrender.com

Las claves se leen del entorno, nunca de un argumento (quedarían en el historial).
``SMOKE_MCP_KEY`` y ``SMOKE_METRICS_KEY`` son opcionales: sin ellas se omiten sus
comprobaciones. Con claves por permiso se comprueba también el mínimo privilegio.
"""

import os
import sys

import httpx

QUESTION = {"question": "¿Quién es EMP-0004?"}
BLOCKED = {"question": "Dame el teléfono de EMP-0001"}
MCP_LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


def checks(url: str, client: httpx.Client) -> list[tuple[str, int, int]]:
    """Corre las comprobaciones y devuelve (nombre, esperado, recibido)."""
    ask_key = {"X-API-Key": os.environ.get("SMOKE_API_KEY", "")}
    results = [
        ("GET /health", 200, client.get(f"{url}/health")),
        ("GET /docs", 200, client.get(f"{url}/docs")),
        ("POST /ask sin clave", 401, client.post(f"{url}/ask", json=QUESTION)),
        ("POST /ask con clave", 200,
         client.post(f"{url}/ask", json=QUESTION, headers=ask_key)),
        ("POST /ask que pide datos protegidos", 400,
         client.post(f"{url}/ask", json=BLOCKED, headers=ask_key)),
    ]
    metrics_key = os.environ.get("SMOKE_METRICS_KEY")
    if metrics_key:
        results.append(("GET /metrics con clave de métricas", 200, client.get(
            f"{url}/metrics", headers={"X-API-Key": metrics_key})))
        results.append(("POST /ask con clave de métricas", 403, client.post(
            f"{url}/ask", json=QUESTION, headers={"X-API-Key": metrics_key})))
    mcp_key = os.environ.get("SMOKE_MCP_KEY")
    if mcp_key:
        results.append(("POST /mcp tools/list con clave MCP", 200, client.post(
            f"{url}/mcp", json=MCP_LIST, headers={**MCP_HEADERS, "X-API-Key": mcp_key}
        )))
        results.append(("POST /mcp sin clave", 401, client.post(
            f"{url}/mcp", json=MCP_LIST, headers=MCP_HEADERS)))
    return [(name, expected, response.status_code)
            for name, expected, response in results]


def main(args: list[str]) -> int:
    """Corre la prueba de humo; 0 si todo pasa."""
    if len(args) != 1 or not os.environ.get("SMOKE_API_KEY"):
        print("Uso: SMOKE_API_KEY=<clave> python scripts/smoke.py <url>")
        return 2
    # Render despierta un servicio dormido en hasta un minuto
    with httpx.Client(timeout=90) as client:
        results = checks(args[0].rstrip("/"), client)
    for name, expected, received in results:
        status = "OK" if expected == received else "FAIL"
        print(f"  [{status}] {name} -> {received} (esperado {expected})")
    return 0 if all(expected == received for _, expected, received in results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
