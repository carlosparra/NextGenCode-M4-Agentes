# Servidor MCP

Implementado con el SDK oficial de Python (`mcp` 2.3, clase `MCPServer`). El código está
en `app/mcp_server/`: `server.py` declara las capacidades y `__main__.py` elige el
transporte.

## Capacidades

| Tipo | Nombre | Qué hace | Agente |
| --- | --- | --- | --- |
| Herramienta | `vacation_balance` | Días de vacaciones que le quedan a un empleado (LFT art. 76) | `vacation_agent` (ReAct) |
| Herramienta | `department_summary` | Resumen de un área: plantilla, activos, bajas, puestos, antigüedad | `summary_agent` (reflection) |
| Herramienta | `ask_hr` | Pregunta libre; el supervisor delega en el especialista | `hr_agent` (supervisor ReAct) |
| Recurso | `hr://departments` | Departamentos válidos (JSON) | — |
| Prompt | `vacation_review` | Plantilla para que el host explique un saldo en tres viñetas | — |

Las tres herramientas llevan las anotaciones `readOnlyHint: true`,
`destructiveHint: false`, `idempotentHint: true` y `openWorldHint: false`, para que el
host sepa que no modifican nada.

## Esquemas

**Entradas** (validadas por el SDK antes de llegar al agente):

| Herramienta | Parámetro | Regla |
| --- | --- | --- |
| `vacation_balance` | `employee_id` | Requerido, patrón `^EMP-\d{4}$` |
| | `context` | Opcional, máximo 500 caracteres; pasa por las guardas de PII e inyección |
| `department_summary` | `department` | Requerido, 2 a 60 caracteres; se acepta sin acentos (`tecnologia`) |
| `ask_hr` | `question` | Requerido, 1 a `MAX_QUESTION_CHARS` caracteres |

**Salidas** estructuradas (`structuredContent` con `outputSchema`):

- `VacationReport`: `employee_id`, `found`, `name`, `status`, `years_of_service`,
  `entitled_days`, `taken_days`, `balance_days`, `period_start`, `period_end`, `answer`,
  `reasoning` (los `thought` del agente en cada paso), `tools_used`, `model_answer_kept`
  (falso si el código corrigió al modelo) y `usage` (modelo, llamadas, tokens, costo,
  latencia).
- `DepartmentSummary`: `department`, `answer`, `facts`, `reflection_rounds`, `critiques`
  (lo que el crítico pidió corregir en cada vuelta), `accepted`, `fallback` y `usage`.
- `HrAnswer`: `answer`, `intent`, `tools_used`, `reasoning`, `pii_detected` y `usage`.

Todas incluyen el `request_id` para buscar la ejecución en logs y en LangSmith.

## Manejo de errores

| Situación | Lo que ve el host | Registro |
| --- | --- | --- |
| Argumento que no cumple el esquema | `isError: true` con el campo y la regla | Log del SDK |
| Departamento inexistente | `isError: true`: «No existe el departamento 'X'. Existen: ...» | `mcp_tool_call status=not_found` |
| Inyección o PII bloqueada | `isError: true`: «La política de seguridad rechazó la entrada (prompt_injection)» | `input_rejected` + `mcp_tool_call status=rejected` |
| Modelo caído tras los reintentos | `isError: true`: «El modelo no está disponible; intenta en unos minutos» | `mcp_tool_call status=model_unavailable` |
| Error inesperado | `isError: true`: «Error interno. Reporta el request_id ...» (sin detalles internos) | Evento `error` con el tipo de excepción |

Un detalle que encontraron las pruebas: `KeyError` hereda de `LookupError`. Por eso el «no
encontrado» usa una excepción propia (`NotFoundError`) y un error interno nunca se
confunde con uno de usuario ni filtra su mensaje.

## Transportes

| Transporte | Comando | Para qué |
| --- | --- | --- |
| stdio | `python -m app.mcp_server --env-file .env` | Claude Code, VS Code y Claude Desktop en la misma máquina |
| SSE | `python -m app.mcp_server --transport sse --port 8001` | Hosts que aún usan el transporte anterior |
| Streamable HTTP | `python -m app.mcp_server --transport streamable-http --port 8001` | Servidor MCP independiente |
| Streamable HTTP en la API | `https://<servicio>/mcp` con `X-API-Key` | Producción: misma seguridad, escalado y auditoría que la API |

En stdio la salida estándar es del protocolo: los logs JSON van a **stderr**. Los
transportes HTTP independientes escuchan en `127.0.0.1` por omisión y activan la
protección contra DNS rebinding.

## Probarlo

```bash
python scripts/mcp_demo.py                   # stdio local
MCP_API_KEY=... python scripts/mcp_demo.py https://hr-assistant-ebersilva.onrender.com/mcp
python -m pytest tests/test_mcp.py tests/test_mcp_stdio.py -v
```

También sirve el inspector oficial: `npx @modelcontextprotocol/inspector .venv/bin/python
-m app.mcp_server`.

## Ejemplo de una llamada (JSON-RPC por HTTP)

```bash
curl -s https://<servicio>/mcp -H "X-API-Key: $HR_API_KEY" \
  -H 'Accept: application/json, text/event-stream' -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call",
       "params":{"name":"vacation_balance","arguments":{"employee_id":"EMP-0002"}}}'
```

```json
{"jsonrpc": "2.0", "id": 1, "result": {"structuredContent": {
  "employee_id": "EMP-0002", "name": "Luis Pérez", "years_of_service": 5,
  "entitled_days": 20, "taken_days": 4, "balance_days": 16,
  "period_start": "2026-07-19", "period_end": "2027-07-19",
  "reasoning": ["Primero confirmo que el empleado existe y sigue activo.",
                "Calculo los días que le tocan por antigüedad (LFT art. 76).",
                "Reviso cuántos días ya tomó en el periodo vigente."],
  "tools_used": ["get_employee", "compute_entitlement", "get_taken_days"],
  "model_answer_kept": true, "usage": {"model_calls": 4, "cost_usd": 0.00011}}}}
```
