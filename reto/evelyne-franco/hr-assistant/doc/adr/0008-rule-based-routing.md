# ADR 0008: Enrutamiento por regla en código, no por otro modelo

## Contexto

La mayoría de las preguntas de RH son búsquedas simples que un modelo pequeño responde bien; unas pocas piden
comparar o resumir. Usar siempre el modelo grande cuesta de más. Decidir con otro modelo agregaría costo,
latencia y una fuente más de errores.

## Decisión

- `routing.py` expone `route_question(question, settings) -> Route(model, reason)`, una función pura.
- Orden de la regla: `ROUTING=false` da `MODEL_LARGE`; si la pregunta pasa de `ROUTER_MAX_CHARS`, `MODEL_LARGE`;
  si contiene «compara», «resume», «explica», «por qué», «analiza» o «todos», `MODEL_LARGE`; si no, `MODEL_SMALL`.
- La comparación se hace sobre el texto normalizado con `fold_text` (sin mayúsculas ni acentos).
- El motivo (`reason`) se devuelve en `route` de `/ask` y en el evento `agent_run`, sin el texto de la pregunta.
- El modelo se elige una vez por petición; todas las vueltas del bucle usan el mismo.

## Consecuencias

- La decisión es determinista, gratis y se prueba con casos de tabla.
- Una pregunta difícil sin palabra clave y corta irá al modelo pequeño; el motivo en la respuesta y en el log
  permite detectarlo y ajustar la lista de palabras.
- `ROUTING=false` es la línea base de la evaluación de costos.
