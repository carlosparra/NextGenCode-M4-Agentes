# 0017. Trazas de LangSmith obligatorias en Render, opcionales en local

Estado: aceptado. Reemplaza a 0006 en lo que toca a la obligatoriedad; el adaptador de 0006 sigue vigente.

## Contexto

El ADR 0006 hizo las trazas opcionales y el 0013 dejó `LANGSMITH_API_KEY` fuera del Blueprint. `spec/05-reto.md`
cambia el requisito: en producción las trazas en LangSmith son obligatorias y el Blueprint debe declarar
`LANGSMITH_TRACING=true`, `LANGSMITH_PROJECT=<repositorio>` y el secreto `LANGSMITH_API_KEY` con `sync: false`.
En local y en el CI el producto debe seguir funcionando sin clave ni red.

## Decisión

- `render.yaml` fija `LANGSMITH_TRACING=true`, `LANGSMITH_PROJECT=hr-assistant-reto`, `HIDE_INPUTS=true` y
  `HIDE_OUTPUTS=true`, y declara `LANGSMITH_API_KEY` con `sync: false`: Render la pide al crear el Blueprint.
- El adaptador de 0006 no cambia: `build_tracer(settings)` usa el trazador real solo con `LANGSMITH_TRACING=true`
  y clave presente; en cualquier otro caso, `NoopTracer`. Por omisión `LANGSMITH_TRACING=false`, así que en local,
  en las pruebas y en el CI la traza sigue siendo opcional.
- Las trazas llevan en metadatos `request_id`, `client`, `model`, `route` y `environment`; el texto ya pasó por el
  enmascarado de PII (ADR 0014) y entradas y salidas siguen ocultas.

## Consecuencias

- Cada petición en Render se puede seguir por `request_id` del log a LangSmith.
- La obligatoriedad vive en el Blueprint, no en `compliance.enforce`: si alguien borra la clave en Render, la
  aplicación arranca con `NoopTracer` y pierde trazas sin fallar. Se revisa en la comprobación de producción.
- La clave de LangSmith pasa a ser un secreto más que rotar y documentar con mínimo privilegio (`doc/security.md`).
