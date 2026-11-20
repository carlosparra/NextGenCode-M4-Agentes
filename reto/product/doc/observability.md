# Observabilidad del HR Assistant

Tres fuentes, unidas por el mismo `request_id`: el log JSON (stdout, que Render guarda), las trazas de LangSmith y
`GET /metrics`. Ninguna lleva texto de preguntas o respuestas, valores de datos sensibles ni claves. Decisiones:
ADR 0004 (request_id y log), 0005 y 0016 (métricas por proceso), 0006 y 0017 (trazas).

## 1. Rastrear una petición por `request_id`

### De dónde sale el id

- El cliente puede mandar `X-Request-ID` (`[A-Za-z0-9._:-]`, 1 a 128 caracteres); si falta o no es válido, el
  middleware genera un UUID4 (`app/main.py`: `resolve_request_id`).
- Toda respuesta lo trae en el encabezado `X-Request-ID`. `POST /ask` lo trae también en el cuerpo, y los errores
  `500` y `502` en `{"detail": ..., "request_id": ...}`. La página lo muestra debajo de cada respuesta.
- Para soporte, se pide a la persona el `request_id` que ve en pantalla.

### En el log de Render

Render guarda la salida estándar del contenedor: una línea JSON por evento, con `ts`, `service`, `event` y
`request_id`. En el panel del servicio `hr-assistant-reto`, sección Logs, se busca el `request_id` como texto. Con
dos workers las líneas de ambos procesos salen mezcladas; el `request_id` las separa.

| Evento | Cuándo aparece | Campos útiles |
| --- | --- | --- |
| `request` | Siempre, una vez por petición, al final | `method`, `path`, `status`, `latency_ms`, `client` (o `null`), `cost_usd` (solo `/ask`; 0 si no llegó al agente o fue un acierto de caché) |
| `audit` con `action: tool_call` | Por cada herramienta que pide el agente | `tool`, `args`, `ok`, `client` |
| `audit` de seguridad | Cuando actúa una guarda | `action` (`auth_failed`, `rate_limited`, `input_rejected`, `pii_detected`, `output_blocked`), `types` y `where` si aplican, `client` |
| `agent_run` | Cuando corrió el agente (no en un acierto de caché ni en un rechazo) | `model`, `route`, `steps`, `tools`, `input_tokens`, `output_tokens`, `history_sent`, `cached_calls`, `stopped`, `latency_ms`, `cost_usd` |
| `error` | Excepción inesperada (500) o fallo del modelo (502) | `error_type` (solo el nombre de la clase) |

Lectura rápida de una petición:

1. `request.status` dice cómo terminó. `401` o `429`: buscar el `audit` `auth_failed` o `rate_limited`. `400`:
   `audit` `input_rejected` (con `where`) o `pii_detected` con `PII_POLICY=block`.
2. Sin `agent_run` y con `status` 200: fue un acierto de la caché de respuestas (`cost_usd` 0).
3. Con `agent_run`: comparar `agent_run.latency_ms` (agente y modelo) contra `request.latency_ms` (toda la
   petición). `stopped: max_steps` indica que el agente agotó `AGENT_MAX_STEPS`.
4. `error` con `error_type: ModelUnavailable` junto a un `502`: falló la llamada a Cloudflare AI Gateway. El log no
   dice por qué (caída, timeout o 401 por configuración); ver la lección operativa de abajo.
5. `audit pii_detected` con `where: answer` en una pregunta sin datos sensibles: el modelo devolvió algo con forma
   de dato personal (por ejemplo, un teléfono inventado) y el enmascarado lo tapó (`doc/security.md`, "Sin datos
   inventados").

### Lección operativa: un 502 que era configuración

Tras publicar, `/ask` respondía 502 y el log solo mostraba `error` con `error_type: ModelUnavailable`, sin el código
de estado de Cloudflare. La causa era un valor pegado con comillas en Render > Environment: las comillas quedaron
dentro del valor y rompieron la URL del gateway, y Cloudflare respondió 401 «Account ID missing from request path».

- `ModelUnavailable` agrupa a propósito todo fallo del proveedor (ADR 0008), así que un error de configuración se
  ve igual que una caída.
- Ante 502 justo después de publicar o de cambiar una variable: revisar en Render que `CF_ACCOUNT_ID`,
  `CF_GATEWAY_ID`, `CF_API_TOKEN` y `CF_AIG_TOKEN` estén sin comillas ni espacios, y que el token del gateway sea
  vigente si el gateway tiene "Authenticated Gateway" encendido.
- Si eso no basta, mirar los logs del propio AI Gateway en el panel de Cloudflare, que sí muestran el código de
  estado de cada llamada.
- Después de corregir, `verification production <url>` confirma que `/ask` vuelve a 200.

### En LangSmith

Con `LANGSMITH_TRACING=true` (obligatorio en Render), cada corrida del agente queda en el proyecto
`hr-assistant-reto` como un árbol: `agent_run` (chain) con sus llamadas `llm` y sus `tool`.

- Metadatos de cada corrida: `request_id`, `client`, `model`, `route`, `environment`; `agent_run` agrega
  `cost_usd` al terminar. Tags: `environment:<valor>` y `route:<valor>`.
- Para encontrar una petición, filtrar el proyecto por metadato: clave `request_id`, valor el id. En la barra de
  filtros equivale a `and(eq(metadata_key, "request_id"), eq(metadata_value, "<id>"))`.
- Para ver todo lo enviado al modelo grande en producción: `has(tags, "environment:production")` y el tag de
  `route` que corresponda.
- Con `HIDE_INPUTS=true` y `HIDE_OUTPUTS=true` (exigidos por compliance en producción) no se ve el texto: solo la
  estructura, los tiempos, los tokens y los metadatos. Eso basta para ver qué paso tardó, cuántas vueltas hubo y
  cuánto costó.
- No hay traza cuando la petición no llegó al agente: 401, 429, 422, 400 o acierto de caché. En esos casos la
  fuente es el log.

## 2. Qué mide `GET /metrics`

Exige `X-API-Key`. Devuelve las métricas **del proceso que respondió** (`pid`); con `WEB_CONCURRENCY=2` hay que
llamarlo varias veces y agrupar por `pid` para ver los dos procesos. Se reinician con cada despliegue o reinicio.
Las peticiones a `/metrics` no se cuentan.

| Campo | Qué mide |
| --- | --- |
| `pid` | Proceso que respondió |
| `requests` | Peticiones atendidas por el proceso |
| `error_rate` | Fracción de respuestas 5xx (los 4xx no cuentan: son errores del cliente) |
| `errors_by_status` | `{"4xx": n, "5xx": n}` |
| `latency_ms` | `p50` y `p95` por rango más cercano sobre las últimas 10 000 peticiones |
| `tokens` | `input` y `output` acumulados del agente |
| `cost_usd` | Costo acumulado de las respuestas de `/ask` |
| `cost_usd_per_request` | `cost_usd` entre las respuestas de `/ask` con costo (los aciertos de caché cuentan con 0) |
| `security` | `auth_failures`, `rate_limited`, `inputs_rejected`, `pii_detections`, `outputs_blocked` |
| `cache` | `hits` y `misses` de la caché de respuestas (en 0 si está apagada) |
| `slo` | `p95_ms_target` (`SLO_P95_MS`) y `met` |

Señales que conviene vigilar:

- `error_rate` mayor que 0: revisar en el log los `error` y su `error_type`; si es `ModelUnavailable` justo
  después de un cambio de configuración, seguir la lección operativa de la sección 1.
- `security.auth_failures` que sube rápido: alguien prueba claves; `rate_limited` alto: un cliente pasa su límite.
- `security.outputs_blocked` mayor que 0: el modelo intentó devolver algo parecido a un secreto; revisar el
  `request_id` en el log.
- `security.pii_detections` que sube sin que el personal escriba datos sensibles: el modelo puede estar inventando
  datos; buscar `audit pii_detected` con `where: answer`.
- `cache.hits / (hits + misses)` bajo con `RESPONSE_CACHE_TTL_SECONDS=300`: las preguntas no se repiten o los
  workers reparten los aciertos.
- `cost_usd_per_request` que sube: más preguntas enrutadas al modelo grande, historiales más largos o un prompt de
  sistema más largo (`doc/cost-analysis.md`).

## 3. SLO

| Objetivo | Meta | Dónde se mide |
| --- | --- | --- |
| Latencia | p95 por debajo de `SLO_P95_MS` (2000 ms por omisión) | `slo.met` de `/metrics`, por proceso |
| Errores del servidor | `error_rate` en 0 | `/metrics` y eventos `error` del log |
| Carga (criterio de aceptación) | 40 preguntas, 8 a la vez: ningún 5xx, 95 % o más de 200 y p95 por debajo de 5 s | `verification load` y `verification load <url>` contra Render |

- El SLO de `/metrics` se evalúa por proceso y sobre la ventana de latencias del proceso, no sobre un periodo de
  calendario; es un indicador para operar, no un compromiso contractual.
- La latencia incluye las peticiones rechazadas (rápidas) y los aciertos de caché, que bajan el p95; para ver la
  latencia del modelo, usar `agent_run.latency_ms` en el log o los tiempos de la corrida en LangSmith.
- En el plan gratuito de Render el primer acceso tras un periodo inactivo arranca el contenedor y puede romper el
  p95; `verification production` y `verification load` se corren con el servicio ya despierto.
