# Servidor MCP

El servidor expone las capacidades del HR Assistant a cualquier host MCP. Usa el SDK
oficial de MCP para Python y los dos transportes: stdio y HTTP.

## Herramientas

Cada herramienta ejecuta por dentro un agente LangGraph y devuelve una salida
estructurada (un modelo Pydantic con esquema), que incluye el razonamiento del agente.

| Herramienta | Argumento | Agente interno | Patrón |
| --- | --- | --- | --- |
| `ask_hr` | `question` | Supervisor que elige entre los tres especialistas | Supervisor y ReAct |
| `vacation_balance` | `employee_id` (`EMP-0001`) | `vacation_agent`: el modelo razona y pide `get_vacation_balance`; la cifra sale del cálculo de la LFT | ReAct |
| `department_summary` | `department` | `summary_agent`: reúne hechos, redacta, critica en código y revisa hasta dos veces | Reflexión |

Campos comunes de la respuesta: `answer`, `agent`, `reasoning`, `tools_used`, `steps`,
`model`, `cost_usd` y `request_id`. `vacation_balance` agrega `eligible`,
`years_of_service`, `entitled_days`, `taken_days`, `remaining_days`, `period_start` y
`period_end`.

También hay un recurso, `hr://departments` (la lista de departamentos), y un prompt,
`vacation_review`.

### Cómo se ve el razonamiento

`department_summary("Tecnología")` con el modelo simulado devuelve en `reasoning`:

```
Crítica: falta mencionar a Ana López; falta mencionar a Jorge Díaz.
Crítica: sin observaciones.
Revisiones: 1.
```

El primer borrador no pasó la crítica, el modelo lo corrigió y el segundo sí pasó.

## Conectar un host

### stdio (local)

```bash
cd AlbertoRayon_reto
claude mcp add hr-assistant -- uv run python -m app.mcp_server
```

O deja que Claude Code lea `.mcp.json` al abrir la carpeta. En Claude Desktop o VS
Code, el comando es el mismo: `uv run python -m app.mcp_server` con esta carpeta como
directorio de trabajo.

Por stdio el log va a stderr, porque stdout es el canal del protocolo.

### HTTP (remoto)

```bash
claude mcp add --transport http hr-assistant https://<servicio>.onrender.com/mcp \
  --header "X-API-Key: <clave con permiso mcp>"
```

El transporte es HTTP sin estado con respuestas JSON: cualquier copia del servicio
atiende cualquier llamada.

## Seguridad del MCP

- `/mcp` pasa por el mismo middleware que la API: clave, permiso `mcp`, límite por
  cliente y `request_id`.
- Protección contra DNS rebinding: solo se aceptan los hosts locales, los de
  `MCP_ALLOWED_HOSTS` y el de Render.
- Las herramientas usan el mismo `HRService`: mismas guardas de entrada y de salida.
- Los errores se devuelven como errores de herramienta con un mensaje claro, sin
  detalles internos.

## Probarlo sin un host

```bash
uv run pytest tests/test_mcp.py -v
```

Las pruebas cubren el servidor en proceso, por HTTP con clave y por stdio lanzando el
proceso real.
