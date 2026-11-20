# ADR 0015: Una traza raíz por petición, con agentes de código sin texto

## Contexto

En producción, la detección de PII de la entrada no aparecía en LangSmith: ocurría en `main.py` antes de que
empezara la traza `agent_run`, así que su span `security` quedaba suelto. Con varios agentes por petición (ADR 0014)
el problema crecía: cada etapa podía quedar como una traza independiente y no había forma de ver una petición
completa. Además, `HIDE_INPUTS` y `HIDE_OUTPUTS` eran la única barrera para que el texto no llegara a la traza.

## Decisión

- `RequestPipeline.run` abre **un solo run raíz** `request` (tipo `chain`) con `Tracer.traceable`. Dentro,
  `RequestPipeline._stage` abre un run hijo `agent.<nombre>` por cada agente, en orden: `agent.guard`,
  `agent.supervisor`, `agent.directory` o `agent.policy`, y `agent.reviewer`.
- El anidamiento sigue el contexto de ejecución de `langsmith.traceable`: el span `security` de la entrada queda en
  `agent.guard`, los de la salida en `agent.reviewer`, la llamada del supervisor es un run `llm` dentro de
  `agent.supervisor`, y el especialista lleva dentro `agent_run`, sus runs `llm` y sus herramientas (incluida la
  consulta en código de `search_policy`).
- Todos los runs llevan `request_id` y `client`. El especialista recibe además `specialist` y `supervisor_route` al
  abrirse; el raíz los recibe con `Tracer.annotate` (agrega metadatos al run abierto), porque se abre antes de que el
  supervisor decida. Nunca la clave.
- El raíz y los runs `agent.guard`, `agent.supervisor` y `agent.reviewer` trazan funciones **sin parámetros**: el
  texto vive en `RequestContext` y su salida es un resumen (`GuardResult.summary`, `Decision.summary`,
  `Review.summary`, y especialista, motivo y agentes en el raíz).
- Con `LANGSMITH_TRACING=false` o sin clave, `traceable` es la identidad y `annotate` no hace nada; `langsmith` no se
  importa.

## Consecuencias

- Una petición es un árbol en LangSmith y se encuentra por `request_id`; los controles de seguridad se ven dentro
  del agente que los registró. Lo comprueba `tests/test_root_trace.py` con un trazador espía.
- Los agentes de código no dependen de `HIDE_INPUTS` ni `HIDE_OUTPUTS` para no exponer texto.
- Los runs del especialista (`agent_run`, `llm` y herramientas) **sí** reciben la pregunta y el historial limpios,
  y el run `llm` devuelve la salida cruda del modelo, anterior al `reviewer`. Por eso la compliance sigue exigiendo
  `HIDE_INPUTS=true` y `HIDE_OUTPUTS=true` en producción (ADR 0012).
- `Tracer.annotate` depende de `langsmith.run_helpers.get_current_run_tree`; si LangSmith cambia esa API, el raíz se
  queda sin `specialist` y `supervisor_route`, pero el especialista los conserva.
- Hay un nivel más de anidamiento (`request` y `agent.*`) que antes; el costo es despreciable frente a la llamada
  al modelo.
