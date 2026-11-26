# Observabilidad

La pregunta que debe poder responderse con datos es: ¿qué pasó con la petición X?

## Un id por petición

- Si el cliente manda `X-Request-ID` (letras, números, `.`, `:`, `_` o `-`, hasta 64
  caracteres), se conserva; si no, se genera un UUID.
- El id vuelve en la cabecera `X-Request-ID`, en el cuerpo de `/ask`, en cada línea
  del log, en la respuesta de cada herramienta MCP y en los metadatos de la traza.
- El portal lo muestra junto a cada respuesta, para pasarlo a soporte.

## Log estructurado

Una línea JSON por evento en la salida estándar (por stdio va a stderr, para no
romper el protocolo MCP). Todas llevan `ts`, `service`, `event`, `request_id`,
`client` y `channel` (`http`, `mcp-http` o `mcp-stdio`).

| Evento | Campos | Cuándo |
| --- | --- | --- |
| `request` | `method`, `path`, `status`, `latency_ms` | Cada petición HTTP |
| `agent_run` | `agent`, `steps`, `tools`, tokens, `model`, `route`, `cost_usd`, `cache`, `pii_types`, `stopped` | Cada corrida de agente |
| `audit` | `action` y su detalle | Ver la tabla de auditoría en [`security.md`](security.md) |
| `error` | `error_type` | Una excepción; nunca el mensaje completo |

El log nunca lleva el texto de la pregunta ni de la respuesta, ni claves: solo
tamaños (`question_chars`), tipos de dato personal y nombres de herramientas. Hay
pruebas que lo comprueban (`test_logs_are_json_without_the_question_text`,
`test_key_never_appears_in_logs`).

Ejemplo real de una petición, de principio a fin: [`../evidence/logs.txt`](../evidence/logs.txt).

### Depurar una petición

```bash
# Todo lo que pasó con una petición, en orden
grep '"request_id": "demo-123"' servicio.log | jq -c '{event, action, agent, tool, status}'
```

## Métricas

`GET /metrics` (permiso `metrics`) devuelve las métricas de este proceso:

| Tipo | Métrica |
| --- | --- |
| Técnicas | `requests`, `error_rate`, `latency_ms.p50`, `latency_ms.p95`, `slo.met` |
| De costo | `tokens.input`, `tokens.output`, `cost_usd`, `baseline_cost_usd`, `savings_pct` |
| De negocio | Corridas por agente y por modelo, aciertos de caché |
| De seguridad | `auth_failed`, `scope_denied`, `rate_limited`, `guard_blocked`, `pii_masked`, `output_guard_flag` |

- El p95 importa más que el promedio: dice cómo le va al 5 % con peor experiencia.
  `slo.met` es verdadero si el p95 está por debajo de `SLO_P95_MS`.
- `baseline_cost_usd` es lo que habrían costado los mismos tokens en el modelo
  grande; `savings_pct` es el ahorro del enrutamiento en vivo.
- `GET /metrics/prometheus` expone lo mismo en formato de texto para Prometheus o
  Grafana.
- `GET /dashboard` es un tablero que lee `/metrics` cada 5 segundos.

Cada respuesta de `/ask` trae además su propio costo: `model`, `route`,
`input_tokens`, `output_tokens`, `cached_calls` y `cost_usd`.

## Trazas en LangSmith

Con `LANGSMITH_TRACING=true` y `LANGSMITH_API_KEY`:

- LangGraph registra cada grafo como una traza: el supervisor, el especialista y
  cada nodo, anidados.
- `ModelCaller` agrega cada llamada al modelo como un paso `llm`, con
  `usage_metadata` (tokens de entrada y de salida) y el nombre del modelo, para que
  LangSmith muestre tokens y costo.
- Cada herramienta es un paso `tool`.
- La traza lleva `request_id`, `client` y `channel` en sus metadatos.

Con `HIDE_INPUTS=true` y `HIDE_OUTPUTS=true` (obligatorio en producción) no se envía
el texto de preguntas ni respuestas. Por eso en producción las trazas se buscan por
`request_id`: en LangSmith, filtro `metadata` con clave `request_id`.

Sin la clave, el producto funciona igual y no intenta conectarse.

Si tu cuenta de LangSmith es de la región EU, agrega
`LANGSMITH_ENDPOINT=https://eu.api.smith.langchain.com`.
