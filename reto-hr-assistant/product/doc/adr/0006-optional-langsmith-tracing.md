# 0006. Trazas opcionales en LangSmith detrás de un `Tracer`

Estado: propuesto

## Contexto

Se quieren trazas de cada corrida del agente, cada llamada al modelo y cada herramienta, ligadas al
`request_id`. Pero sin clave el producto debe funcionar igual y sin intentar conectarse, las pruebas no pueden
usar red, y por omisión no se deben enviar preguntas ni respuestas a un tercero.

## Decisión

Un `Tracer` encapsula LangSmith. Está activo solo si `LANGSMITH_TRACING=true` y existe `LANGSMITH_API_KEY`;
si no, `wrap(fn, ...)` devuelve la misma función y `request_scope(...)` es un `nullcontext`, sin crear cliente.
Activo, envuelve con `@traceable` `Agent.run` (`chain`), `complete` (`llm`) y cada herramienta (`tool`), usa
un `Client` que oculta entradas y salidas según `HIDE_INPUTS`/`HIDE_OUTPUTS` (ambos `true` por omisión) y abre
`tracing_context(metadata={"request_id": ...})` por petición. La clave solo la lee el cliente del entorno;
`Settings` guarda únicamente si está presente.

## Consecuencias

- `agent.py` y `llm.py` no dependen de LangSmith; cambiar de proveedor de trazas es cambiar `tracing.py`.
- Sin clave no hay red ni costo; las pruebas del modo activo simulan `langsmith`.
- Con `HIDE_*` en `true` las trazas sirven para tiempos y estructura, no para ver el contenido; mostrarlo es una
  decisión explícita de quien opera.
- Se agrega `langsmith` a `requirements.txt`.
