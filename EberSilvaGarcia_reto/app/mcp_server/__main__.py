"""Punto de entrada del servidor MCP independiente.

Uso::

    python -m app.mcp_server                       # stdio (Claude Code, VS Code...)
    python -m app.mcp_server --transport sse --port 8001
    python -m app.mcp_server --transport streamable-http --port 8001

En stdio la salida estándar es del protocolo: todos los logs van a stderr.
Para producción el mismo servidor también se monta en la API (``/mcp``),
protegido con la clave por cliente.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mcp.server.transport_security import TransportSecuritySettings

from app.clock import SystemClock
from app.config import ConfigError, load_settings
from app.mcp_server.server import build_mcp_server
from app.observability.logs import JsonLogger
from app.service import HrService, build_services


def load_env_file(path: Path) -> dict[str, str]:
    """Lee un archivo ``.env`` sencillo (``CLAVE=valor``) sin imprimirlo.

    :param path: Ruta al archivo
    :type path: pathlib.Path
    :return: Variables leídas
    :rtype: dict[str, str]
    """
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            name, _, value = line.partition("=")
            values[name.strip()] = value.strip().strip("'\"")
    return values


def main(argv: list[str] | None = None) -> int:
    """Arranca el servidor MCP con el transporte elegido.

    :param argv: Argumentos de línea de comandos
    :type argv: list[str] | None
    :return: Código de salida
    :rtype: int
    """
    import os  # pylint: disable=import-outside-toplevel

    parser = argparse.ArgumentParser(prog="python -m app.mcp_server")
    parser.add_argument(
        "--transport", choices=("stdio", "sse", "streamable-http"), default="stdio"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Archivo .env con la configuración (opcional)",
    )
    args = parser.parse_args(argv)
    if args.env_file:
        for name, value in load_env_file(args.env_file).items():
            os.environ.setdefault(name, value)
    clock = SystemClock()
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"Configuración inválida: {exc}", file=sys.stderr)
        return 2
    logger = JsonLogger(
        settings.service_name + "-mcp",
        clock,
        stream=sys.stderr,
        audit_path=settings.audit_log_path,
    )
    service = HrService(build_services(settings, clock, logger))
    server = build_mcp_server(service)
    logger.event(
        "startup",
        transport=args.transport,
        provider=settings.model_provider,
        tracing=service.s.tracer.enabled,
    )
    if args.transport == "stdio":
        server.run("stdio")
        return 0
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[f"{args.host}:*", "localhost:*", "127.0.0.1:*"],
        allowed_origins=["http://localhost:*", "http://127.0.0.1:*"],
    )
    server.run(
        args.transport, host=args.host, port=args.port, transport_security=security
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
