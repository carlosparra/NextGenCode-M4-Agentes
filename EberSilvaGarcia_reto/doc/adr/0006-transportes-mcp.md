# 0006. Transportes MCP: stdio local y Streamable HTTP sin estado en la API

- Estado: aceptada
- Fecha: 2026-11-24

## Contexto

Los hosts locales (Claude Code, VS Code, Claude Desktop) arrancan servidores por stdio. Un
host remoto necesita HTTP. SSE es el transporte anterior de la especificación.

## Decisión

- `python -m app.mcp_server` soporta `stdio` (por omisión), `sse` y `streamable-http`.
- En producción, el mismo `MCPServer` se monta en la API en `/mcp` con Streamable HTTP
  **sin estado** (`stateless_http=True`, respuestas JSON). Así escala igual que la API y
  hereda su seguridad: clave con permiso `mcp`, límite, auditoría y protección contra
  DNS rebinding con los hosts permitidos (incluido `RENDER_EXTERNAL_HOSTNAME`).
- En stdio, los logs van a stderr para no corromper el protocolo.

## Consecuencias

- Un solo despliegue sirve a la página, a la API y a hosts MCP remotos.
- Sin sesiones MCP en memoria: no hace falta afinidad de sesión entre copias.
