# 0003. Un solo agente con bucle de herramientas con tope

Estado: propuesto

## Contexto

El agente alterna entre pedir herramientas y responder. Sin límite, un modelo confundido podría llamar
herramientas para siempre, con costo y latencia sin control. El contrato además espera conteos exactos de pasos.

## Decisión

Un solo agente con dos herramientas de solo lectura (`get_employee`, `search_by_department`) en un registro
nombre a función. Un paso es una llamada al modelo. En cada paso: si el modelo responde, se termina; si pide una
herramienta, se ejecuta, se anota en `tools_used` y su resultado se agrega como mensaje `user` que empieza con
`Resultado de la herramienta: `. Los errores (JSON inválido, herramienta desconocida, argumentos malos) se
devuelven al modelo como resultado y consumen el paso. Al llegar a `AGENT_MAX_STEPS` sin respuesta se devuelve
exactamente `No pude completar la respuesta. Intenta con una pregunta más concreta.`

## Consecuencias

- Costo y tiempo por pregunta acotados; con el tope por omisión (3) cabe una herramienta y una respuesta.
- Preguntas que necesiten varias herramientas pueden caer en la respuesta de respaldo; se ajusta el tope por
  configuración.
- Agregar herramientas es sumar entradas al registro, sin cambiar el bucle.

## Hallazgo en producción y corrección

### Hallazgo

Las trazas de LangSmith mostraron que, con el modelo real de 8B, el agente llegaba al tope de pasos: tras
recibir un mensaje `Resultado de la herramienta`, volvía a pedir herramientas en lugar de responder.

- `request_id` 36da9f90, e42baa20 y f5196cb5: `department_summary`, luego `get_employee` o `department_summary`
  otra vez, y tope.
- `request_id` 2beef4a4: pregunta con `[EMAIL]`, tres herramientas seguidas y tope.

El tope cumplió su función (cortó el bucle y acotó costo y latencia), pero la persona no recibía respuesta, solo
el mensaje de respaldo.

### Corrección

Se cambió únicamente `SYSTEM_PROMPT` en `app/agent.py`; el bucle y el tope no cambian. Se agregó un bloque de
reglas:

- Usa una sola herramienta salvo que falte información.
- Tras un `Resultado de la herramienta`, responde de inmediato con `{"answer": ...}` si ya tienes los datos.
- Responde solo la última pregunta.
- `[EMAIL]`, `[PHONE]`, `[CURP]`, `[RFC]` y `[CARD]` son datos ocultos y no se buscan con herramientas.

La prueba `tests/test_agent_tools.py::test_system_prompt_tells_the_model_to_answer_after_a_tool_result` fija la
corrección comprobando las frases clave del prompt.

### Consecuencias de la corrección

- Calidad: `evaluate` se mantiene en 100 %.
- Costo: como el prompt es más largo, en el set de evaluación con palancas el costo pasa de 0.000225 a
  0.000267 USD y los tokens de entrada de 2860 a 3805.
- Limitación: las pruebas usan el modelo simulado, que no reproduce el comportamiento del modelo de 8B. La
  confirmación con el modelo real se hace revisando las trazas de LangSmith después de publicar: se espera que
  baje la proporción de respuestas de respaldo por tope.
