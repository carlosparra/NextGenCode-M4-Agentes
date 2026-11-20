# Observabilidad

## Trazas en LangSmith

Con `LANGSMITH_TRACING=true` y `LANGSMITH_API_KEY`, cada ejecución del agente queda como una traza con estos
pasos: la llamada a `/ask`, cada vuelta del bucle, cada llamada al modelo y cada herramienta. En los metadatos
van `request_id`, `client`, el modelo elegido y el motivo del enrutador.

En producción, compliance exige `HIDE_INPUTS=true` y `HIDE_OUTPUTS=true`: la traza conserva la estructura, los
tiempos y los tokens, pero no el texto de las preguntas ni de las respuestas, que pueden contener datos de
empleados. Así se puede depurar sin exponer información sensible a un tercero.

## Logging estructurado con correlation ID

- El middleware asigna un `X-Request-ID` a cada petición, o respeta el que mande el cliente. Lo regresa en la
  respuesta y lo pone en todos los eventos del log.
- Cada evento es una línea JSON con `ts`, `service`, `event`, `request_id` y `client`:
  - `request`: método, ruta, status y `latency_ms`.
  - `agent_run`: pasos, herramientas, tokens, modelo, `route`, `cached_calls` y `cost_usd`.
  - `audit`: cada llamada a una herramienta, con sus argumentos.
  - `error`: el tipo de error, sin secretos.
- La pregunta no se registra; solo su largo (`question_chars`).

Este es un evento real de la evaluación:

```json
{"event": "agent_run", "request_id": "5c417260-...", "client": "factory", "steps": 2,
 "tools": ["search_by_department"], "input_tokens": 166, "output_tokens": 42,
 "model": "@cf/meta/llama-3.1-8b-instruct-fast", "route": "simple_question", "cost_usd": 2.36e-05}
```

Para depurar en producción: toma el `request_id` de la respuesta, búscalo en Render → Logs y abre en LangSmith
la traza que tenga ese mismo `request_id` en sus metadatos.

## Métricas

`GET /metrics` exige clave y regresa las métricas del proceso:

| Métrica | Uso |
| --- | --- |
| `requests`, `error_rate` | Volumen y tasa de errores |
| `latency_ms.p50`, `latency_ms.p95` | Latencia |
| `slo.p95_ms_target`, `slo.met` | Si se cumple el objetivo de p95 |
| `tokens.input`, `tokens.output` | Consumo del modelo |
| `cost_usd` | Costo acumulado; es una métrica de negocio |

Además, cada respuesta de `/ask` incluye su propio `cost_usd`, así que el costo se mide por petición.

## Limitaciones

- Las métricas viven en la memoria de cada proceso y se reinician al reiniciar el servicio. Para varias
  instancias habría que exportarlas a Prometheus o a OpenTelemetry.
- El tablero de seguimiento es el de LangSmith, que muestra latencia, tokens y errores por proyecto. No hay un
  tablero propio.
