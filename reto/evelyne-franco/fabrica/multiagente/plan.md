# Plan del HR Assistant · Reto: multi-agente en producción y traza raíz

Base: el producto de la spec 05, ya publicado en Render (planes anteriores en `output/corrida-1-produccion/plan.md` y
`output/corrida-2-reto/plan.md`). Esta vuelta agrega solo lo que pide `spec/06-multiagente.md`: los agentes `guard`,
`supervisor`, `directory`, `policy` y `reviewer` en cada `POST /ask`, y un run raíz `request` por petición en LangSmith.
**Regla de oro: nada de lo que ya pasa puede dejar de pasar**, y los campos de `/ask` y las llaves de `/metrics` que ya
existen no cambian.

Reparto (según `hooks/permissions.py` y `.claude/skills/multiagente/SKILL.md`):

- `qa-unit`: primero las pruebas en `product/tests/` (deben fallar antes del código), incluida la de la traza raíz.
- `developer`: puntos 1 a 5 y la parte de log y métricas del punto 7, en `product/app/` y `product/data/`.
- `observability`: punto 6 (traza raíz) sobre el código de developer, y `product/README.md`. Va después, no en
  paralelo.
- `architect`: cuando las compuertas pasen, el punto 8: `doc/architecture.md`, ADR
  `0014-supervisor-rules-first-and-specialists.md`, ADR `0015-root-trace-per-request.md` y `doc/security.md`. En esta
  vuelta solo se escribe este plan.
- `deploy` y `qa-e2e`: sin cambios obligatorios. No hay configuración nueva, el `Dockerfile` ya copia `data/` y la
  página no cambia.

## Decisiones que necesitan aprobación explícita

1. **Escenario del número inventado.** La regla del punto 4 compara números completos contra las políticas
   consultadas. El escenario usa la pregunta de aguinaldo con un especialista simulado que contesta «30 días de
   salario» (30 no aparece en la política) y comprueba que la respuesta final no contiene «30 días» y sí contiene
   «15 días de salario». La debilidad de comparar solo números queda documentada en `doc/security.md` y en el ADR 0014.
2. **Spans `security` con `control=tool_args`.** Ocurren mientras corre el especialista (el modelo pide la herramienta),
   así que quedan dentro de `agent.directory` o `agent.policy`, no dentro de `agent.reviewer`. Dentro de
   `agent.reviewer` quedan los de la validación de salida (`secret`, `pii`, `output_invalid`) y los de `ungrounded`.
3. **Si el modelo del supervisor no responde**, la petición da 502 como hoy (`ModelUnavailable`); no se usa
   `directory` por omisión, para no ocultar una caída del gateway.

## Módulos

Solo se listan los archivos de `product/app/` nuevos o cambiados.

- `policies.py` (**nuevo**, developer): `PolicyBook.from_file(path)` carga `data/policies.json`. `find(topic)` busca
  por `topic` o `keywords` con `fold_text`; `match_question(text)` devuelve el tema cuya palabra clave aparece en la
  pregunta (con límites de palabra; si hay varias, gana la palabra clave más larga y luego el orden del archivo);
  `search_policy(topic)` devuelve `{"topic", "text"}` o `{"error": "tema no encontrado", "topics": [...]}`.
- `prompts.py` (**nuevo**, developer): `DIRECTORY_PROMPT` (el `SYSTEM_PROMPT` actual, movido sin cambios),
  `SUPERVISOR_PROMPT` (clasifica y responde solo `{"specialist": "directory"}` o `{"specialist": "policy"}`) y
  `POLICY_PROMPT` (solo `search_policy`; si la pregunta no es de políticas, lo dice y menciona Recursos Humanos).
- `supervisor.py` (**nuevo**, developer): `route_by_rules(question, departments, policies)`, pura, aplica
  `rule:employee`, `rule:department` y `rule:policy` en ese orden. `Supervisor.decide(question, model)` usa las reglas y,
  si ninguna aplica, hace **una** llamada a `MODEL_SMALL` con `[system SUPERVISOR_PROMPT, user question]`, sin
  historial; respuesta inválida da `directory` con `model_invalid`. Devuelve `Decision(specialist, route, topic,
  completion)`.
- `reviewer.py` (**nuevo**, developer): `ungrounded_ids(answer, question, known_ids)` y
  `ungrounded_numbers(answer, policy_texts)`, puras (`\d+` completos, comparados como conjuntos). `Reviewer.review(...)`
  corre `screen_answer` (secretos, PII, vacía), luego la comprobación contra los datos según el especialista y al
  final `truncate_answer`; cada hallazgo va a `SecurityAudit` con `stage=output`.
- `guard.py` (**nuevo**, developer): `screen_input(...)`, que es el `_screen_input` de `main.py` movido sin cambios de
  comportamiento. Devuelve `GuardResult(question, history, kinds, injection)`.
- `orchestrator.py` (**nuevo**, developer; observability agrega las trazas): `RequestPipeline.run(question, history,
  request_id, client)` encadena guard, supervisor, enrutador de costo (`route_question` y `window_history`, sin
  cambios), especialista y reviewer. Cada etapa es una función **sin parámetros de texto** que lee y escribe un
  `RequestContext` local de la petición y devuelve un resumen (tipos, conteos, decisiones). Así observability solo
  envuelve cada etapa con `traceable` y no reescribe el flujo.
- `agent.py` (**cambia**, developer): `Agent` gana `name` (`directory` por omisión), un registro de herramientas propio
  y `system_prompt` opcional, todo opcional para que las pruebas actuales lo construyan igual. `directory` solo tiene
  `get_employee` y `search_by_department`; `policy` solo `search_policy` (cualquier otra herramienta es
  `unknown_tool` y `tool_args`). `run(...)` acepta además `specialist`, `supervisor_route`, `prefetched` (resultado de
  `search_policy` que se pone antes de la pregunta con `TOOL_RESULT_PREFIX`, cuenta en `tools_used` y deja `audit`) y
  `seed` (tokens y costo del supervisor, ya con precio de `MODEL_SMALL`). La validación de salida sale del agente y
  pasa al reviewer; `RunState` guarda los textos de las políticas consultadas. `agent_run` se sigue emitiendo una vez
  por petición, ahora con `specialist` y `supervisor_route`, y sus tokens incluyen los del supervisor (iguales a los de
  `/ask`).
- `guardrails.py` (**cambia**): `validate_tool_args` acepta `search_policy` con `topic` de 1 a 60 caracteres sin
  caracteres de control. `validate_answer` se parte en `screen_answer` y `truncate_answer` y se mantiene como la
  composición de ambas (las pruebas de la spec 05 no cambian).
- `llm.py` (**cambia**): `FakeModel` reconoce su papel por el primer mensaje `system`: con `SUPERVISOR_PROMPT` clasifica
  por palabra clave; con `POLICY_PROMPT` responde el `text` de un resultado de herramienta o pide `search_policy`; sin
  mensaje `system` sigue igual que hoy (`directory`). `build_models` le pasa las palabras clave de `PolicyBook`.
- `gateway.py` (**cambia**): si los mensajes ya traen un `system`, lo usa; si no, antepone `DIRECTORY_PROMPT` como hoy.
- `tracing.py` (**cambia**, observability): `Tracer.annotate(metadata)` agrega metadatos al run actual (en LangSmith,
  con el run tree actual e importación perezosa); identidad si las trazas están apagadas.
- `metrics.py` (**cambia**): `record_agents(specialist, route)` bajo el mismo lock; `snapshot()` agrega `specialists`
  (`directory` y `policy` en 0 al inicio) y `supervisor` (los cinco motivos en 0 al inicio).
- `directory.py` (**cambia**): propiedad `ids` para el reviewer.
- `config.py` (**cambia**): `policies_path = "data/policies.json"`, sin variable de entorno nueva (la spec no pide
  configuración).
- `main.py` (**cambia**): `ask` valida la pregunta (422 igual), llama a `RequestPipeline.run` y responde con los campos de
  siempre, `request_id`, `redactions` y los nuevos `specialist`, `agents` y `supervisor_route`. `create_app` acepta
  `policies` opcional. `ASK_FIELDS` no cambia.
- `data/policies.json` (**nuevo**, developer): copia exacta de `spec/policies.json`.
- Sin cambios: `auth.py`, `ratelimit.py`, `compliance.py`, `middleware.py`, `logs.py`, `pii.py`, `security.py`,
  `routing.py`, `pricing.py`, `completion.py`, `text.py`, `clock.py` y `static/index.html`.

## Flujo de una pregunta

1. La página manda `POST /ask {question, history}` con `X-API-Key`, igual que hoy.
2. `ObservabilityMiddleware` asigna el `request_id`; `ClientGuard` responde 401 o 429 como antes.
3. `_validate_question` sobre el texto original (422 igual).
4. Se abre el run raíz `request` (`chain`, sin argumentos de texto, metadatos `request_id` y `client`).
5. **`agent.guard`**: inyección y PII sobre la pregunta y el historial; sus spans `security` de entrada quedan adentro.
   Salida: `{"pii_kinds": [...], "injection": bool}`. Desde aquí solo existe el texto limpio.
6. **`agent.supervisor`**: reglas (`rule:employee`, `rule:department`, `rule:policy`); si ninguna aplica, un run `llm`
   adentro con `MODEL_SMALL`. Salida: `{"specialist": ..., "route": ...}`. Luego `annotate` pone `specialist` y
   `supervisor_route` en el raíz.
7. Enrutador de costo: `route_question` elige el modelo **del especialista** y `window_history` recorta el historial.
8. **`agent.directory` o `agent.policy`** (metadatos con `specialist` y `supervisor_route`): con `rule:policy`, primero
   `search_policy` en código (run de herramienta, `audit` `tool_call`, cuenta en `tools_used`) y el resultado va antes
   de la pregunta. Después el bucle acotado (`AGENT_MAX_STEPS`) con sus runs `llm` y de herramienta; los argumentos
   inválidos dejan `security` `tool_args`. Su salida es un resumen sin la respuesta.
9. **`agent.reviewer`**: secretos, PII y vacía; luego la comprobación contra los datos (`directory`: ids inventados;
   `policy`: números sin respaldo); luego el recorte a `MAX_ANSWER_CHARS`. Los spans `security` de salida quedan
   adentro. Salida: `{"controls": [...], "replaced": bool}`.
10. `agent_run` (sin texto, con `specialist` y `supervisor_route`); `metrics` suma tokens, costo, especialista y motivo.
11. Respuesta 200 con los campos de siempre más `specialist`, `agents = ["guard", "supervisor", <especialista>,
    "reviewer"]` y `supervisor_route`. El middleware emite `request` como siempre.

## Pruebas

Las escribe qa-unit antes que el código. Al `conftest.py` solo se le agregan cosas:

- `SAMPLE_POLICIES` (copia de `spec/policies.json`) en un archivo temporal, inyectado en `build_harness` con `policies`.
- `TreeTracer`: trazador espía que anota cada run al **empezar**, con su padre (pila en `contextvars`, segura con hilos),
  nombre, tipo, metadatos, argumentos y resultado, y que implementa `annotate`. `RecordingTracer` gana `annotate`.
- `SpyModel` que cuenta llamadas y responde lo que se le indique (supervisor o especialista).

Pruebas anteriores que hay que **actualizar** (se agregan llaves nuevas; no es una regresión):

- `test_metrics.py`: el `snapshot()` exacto ahora incluye `specialists` y `supervisor`.
- `test_security.py` línea 236: el conjunto exacto de llaves de `/ask` suma `specialist`, `agents` y
  `supervisor_route`.

Unitarias nuevas:

- `test_supervisor.py`: cada regla; orden entre reglas (`EMP-0001` y `vacaciones` da `rule:employee`; `Ventas` y
  `vacaciones` da `rule:department`); departamento y palabra clave sin acentos ni mayúsculas; las reglas no llaman al
  modelo (espía en 0); sin regla, una sola llamada a `MODEL_SMALL` sin historial; respuesta inválida (texto, JSON sin
  `specialist`, especialista desconocido) da `model_invalid`; los tokens del supervisor suman en `/ask`.
- `test_policies.py`: `search_policy` por `topic`, por palabra clave sin acentos (`DIAS LIBRES`), tema inexistente con
  la lista de temas; argumento vacío, de 61 caracteres o no texto no llama a la herramienta y registra `tool_args`.
- `test_reviewer.py`: id inventado se reemplaza y registra `ungrounded` con `["employee_id"]`; id inexistente escrito por
  la persona no se reemplaza; número que no está en la política se reemplaza por la primera política consultada;
  números de la política pasan; «5» no cuenta dentro de «15»; sin política consultada da el mensaje fijo; una respuesta
  de `directory` no se compara contra políticas; el reemplazo pasa por el recorte; el evento nunca lleva el valor.
- `test_agent.py` (se agrega): `policy` no puede usar `get_employee` y `directory` no puede usar `search_policy`; con
  `prefetched`, el resultado va antes de la pregunta, cuenta en `tools_used` y deja `audit`.
- `test_llm.py` (se agrega): los dos papeles nuevos de `FakeModel` y que sin `system` responde como hoy.
- `test_gateway.py` (se agrega): un `system` recibido se respeta; sin él, se antepone el de hoy.
- `test_metrics.py` (se agrega): `specialists` y `supervisor` empiezan en 0 y suman.
- `test_tracing.py` (se agrega): `annotate` no importa `langsmith` con trazas apagadas.

Traza raíz, `test_root_trace.py` con `TreeTracer`:

- Una sola raíz `request` por petición; `agent.guard`, `agent.supervisor`, el especialista y `agent.reviewer` son sus
  hijos directos y en ese orden.
- Una pregunta con correo deja su span `security` de entrada dentro de `agent.guard`; un `SecretLeakingModel` deja el de
  salida dentro de `agent.reviewer`; el run `llm` del supervisor queda dentro de `agent.supervisor`.
- Todos los runs llevan `request_id` y `client`; el raíz (tras `annotate`) y el especialista, además `specialist` y
  `supervisor_route`; ninguno lleva la clave.
- El raíz, `agent.guard`, `agent.supervisor` y `agent.reviewer` se llaman sin argumentos y su salida no contiene la
  pregunta.

Gherkin nuevo, `tests/features/multiagent.feature` con `test_multiagent_steps.py`:

- «¿Cuántos días de vacaciones tengo?» responde 200 con `specialist = policy`, `supervisor_route = rule:policy`,
  `agents = ["guard", "supervisor", "policy", "reviewer"]` y «12 días hábiles».
- Un espía del especialista `policy` que nunca pide herramientas y responde «30 días» (ver decisión 1): la respuesta no
  contiene «30 días», sí el texto de la política, y hay un evento `security` `ungrounded` con `["policy_number"]`.
- «¿Quién es EMP-0004?» responde con «Jorge Diaz» y `specialist = directory`.
- `/metrics` muestra `specialists` y `supervisor` y conserva las llaves de antes.

Concurrencia: `test_concurrency.py` mezcla 10 preguntas de `directory` y 10 de `policy` (todas con correo) y además
comprueba `specialists` igual a `{"directory": 10, "policy": 10}`.

Fábrica: `verification unit` (cobertura de 80 % o más), `contract` (incluye `test_contract_06.py`), `qa`, `e2e`,
`evaluate` (sin cambiar el set) y, después de publicar, `verification production <url>` y una pregunta de políticas en
la página con su traza en LangSmith.

## Riesgos

- **El supervisor rompe pruebas viejas que leen la primera llamada del modelo** (`test_costs_steps.py` y
  `test_security_steps.py` usan `calls[0]` con historial). Las dos preguntas traen `EMP-####`, así que se resuelven por
  regla y el modelo no se llama de más. Las preguntas sin regla («Hello, how are you?», la de `BadArgsModel`, la de
  `SecretLeakingModel`) agregan una llamada del supervisor que responde algo inválido y caen en `directory` con
  `model_invalid`: el resultado que comprueban esas pruebas no cambia. developer corre `verification unit` antes de
  entregar.
- **Cambian los tokens de preguntas sin regla.** Es lo que pide la spec (la llamada del supervisor suma); ninguna prueba
  actual fija tokens de esas preguntas por HTTP. `test_agent.py` llama a `Agent.run` sin `seed` y no cambia.
- **El escenario del número inventado** (decisión 1): se pide aprobarlo con la pregunta de aguinaldo.
- **La comprobación por números es débil**: un número que sí está en la política pero usado en otro contexto pasa. Es el
  precio de una regla determinista sin modelo; queda en el ADR 0014 y en `doc/security.md`.
- **Falsos reemplazos con el modelo real**: si el modelo escribe un número que no está en la política, la persona recibe
  el texto completo de la política. Es seguro, no incorrecto; `POLICY_PROMPT` pide citar las cifras tal cual.
- **Palabras clave que se pisan** («prima de vacaciones» contiene «vacaciones»): gana la palabra clave más larga y se
  usan límites de palabra; hay prueba.
- **El raíz no sabe el especialista al abrirse**: los metadatos de `traceable` se fijan al decorar. Se resuelve con
  `Tracer.annotate` después del supervisor. Si la versión de `langsmith` no envía esos metadatos al cerrar el run,
  observability lo detecta con la revisión manual en LangSmith y los agrega también al resumen de salida del raíz.
- **Texto en la traza**: las etapas sin texto son funciones sin parámetros sobre un contexto local; la salida del
  especialista es un resumen; los runs `llm` sí ven texto y por eso `HIDE_INPUTS` y `HIDE_OUTPUTS` siguen obligatorios
  en producción (compliance de la sesión 4).
- **Concurrencia**: el `RequestContext` es local a cada petición; la pila del `TreeTracer` y el anidamiento de
  LangSmith usan `contextvars`; los contadores nuevos usan el lock de `Metrics`.
- **Mínimo privilegio roto por un registro compartido**: cada `Agent` tiene su propio registro de herramientas y una
  herramienta ajena se trata como `unknown_tool`; hay pruebas en los dos sentidos.
- **Sin trazas se importa `langsmith`**: `annotate` y los envoltorios nuevos pasan por `Tracer`, que ya es identidad
  cuando está apagado; hay prueba.
- **`evaluate` cambia de calidad**: el único caso sin regla es «¿Qué clima hace hoy en Monterrey?». Con `FakeModel` cae en
  `directory` y la ayuda menciona «empleado»; con el modelo real, si va a `policy`, `POLICY_PROMPT` obliga a mencionar
  Recursos Humanos.
- **Bucles sin fin**: 2 correcciones en compuertas y 2 vueltas de qa-style; después se escala a una persona.

## Resumen

1. Cinco agentes por petición, en orden: `guard` (entrada de la spec 05), `supervisor` (reglas y, si no alcanzan, una
   llamada a `MODEL_SMALL`), un especialista (`directory` o el nuevo `policy`, con herramientas separadas) y `reviewer`.
2. Módulos nuevos: `policies.py`, `prompts.py`, `supervisor.py`, `reviewer.py`, `guard.py` y `orchestrator.py`; cambian
   `agent.py`, `guardrails.py`, `llm.py`, `gateway.py`, `tracing.py`, `metrics.py`, `directory.py`, `config.py` y
   `main.py`.
3. Un run raíz `request` por petición con los cuatro agentes como hijos; las etapas de código no reciben texto y
   `annotate` agrega `specialist` y `supervisor_route` al raíz.
4. qa-unit escribe primero las pruebas (supervisor, `search_policy`, reviewer, traza raíz con un trazador espía,
   Gherkin y concurrencia mezclada) y actualiza dos pruebas que comparan llaves exactas.
5. Se pide aprobar tres decisiones: el escenario del número inventado con aguinaldo, los spans `tool_args` dentro del especialista y el
   502 si falla el modelo del supervisor.
