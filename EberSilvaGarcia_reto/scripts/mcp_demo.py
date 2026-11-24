"""Cliente MCP de demostración: se conecta al servidor y usa las herramientas.

Uso::

    python scripts/mcp_demo.py                       # lanza el servidor por stdio
    export MCP_API_KEY='<clave>'
    python scripts/mcp_demo.py https://hr-assistant-ebersilva.onrender.com/mcp

Muestra el handshake, las herramientas con sus esquemas y una llamada a cada
una, con el razonamiento del agente (ReAct) y las críticas (reflection).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
from mcp import Client, StdioServerParameters
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parent.parent


def server_for(args: list[str]):
    """Servidor local por stdio o remoto por Streamable HTTP con clave."""
    if not args:
        env_file = ROOT / ".env"
        extra = ["--env-file", str(env_file)] if env_file.exists() else []
        return StdioServerParameters(
            command=sys.executable,
            args=["-m", "app.mcp_server", *extra],
            cwd=str(ROOT),
            env=dict(os.environ),
        )
    headers = {"X-API-Key": os.environ.get("MCP_API_KEY", "")}
    http = httpx.AsyncClient(headers=headers, timeout=120)
    return streamable_http_client(args[0], http_client=http)


def show(title: str, data) -> None:
    """Imprime un bloque legible."""
    print(f"\n=== {title}")
    print(json.dumps(data, ensure_ascii=False, indent=2)[:2500])


async def main(args: list[str]) -> int:
    """Recorre las capacidades del servidor."""
    async with Client(server_for(args)) as client:
        info = client.server_info
        print(f"Conectado a {info.name} {info.version}" if info else "Conectado")
        tools = (await client.list_tools()).tools
        show(
            "Herramientas",
            [
                {
                    "name": t.name,
                    "input": t.input_schema["properties"],
                    "read_only": (
                        t.annotations.read_only_hint if t.annotations else None
                    ),
                }
                for t in tools
            ],
        )
        vacation = await client.call_tool(
            "vacation_balance", {"employee_id": "EMP-0001"}
        )
        show("vacation_balance (ReAct)", vacation.structured_content)
        summary = await client.call_tool(
            "department_summary", {"department": "Tecnología"}
        )
        show("department_summary (reflection)", summary.structured_content)
        error = await client.call_tool(
            "department_summary", {"department": "Marketing"}
        )
        show(
            "Error controlado",
            {"is_error": error.is_error, "message": error.content[0].text},
        )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
