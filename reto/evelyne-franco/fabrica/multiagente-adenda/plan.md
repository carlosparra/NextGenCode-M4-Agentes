# Plan del HR Assistant · Adenda 1 de la spec 06: vacaciones por empleado

Base: el sistema multi-agente de la spec 06 (puntos 1 a 8), ya publicado en Render (plan y reporte en
`output/corrida-3-multiagente/`; antes, `output/corrida-1-produccion/` y `output/corrida-2-reto/`). Esta vuelta agrega
solo A1 a A7 de la «Adenda 1 · Vacaciones por empleado». **Nada de lo que ya pasa puede dejar de pasar.** Los campos
de `/ask` y las llaves de `/metrics` no cambian; solo aparece un valor nuevo de `supervisor_route`
(`rule:policy_employee`) y su contador en `supervisor`. No hay configuración nueva.

Reparto (según `hooks/permissions.py`):

- `qa-unit`: primero las pruebas en `product/tests/` (deben fallar antes del código) y las tres pruebas viejas que
  hay que actualizar (ver Pruebas).
- `developer`: A1 a A7 en `product/app/`. `product/data/` no cambia (`employees.json` ya trae `start_date` y `status`).
- `observability`: no hay cambios de traza obligatorios; actualiza `product/README.md` (motivo `rule:policy_employee`,
  herramienta `vacation_days`) y revisa que los runs nuevos lleven `request_id` y `client`.
- `architect`: cuando pasen las compuertas, ADR `0016-vacation-days-in-code.md`, y agregar a `doc/architecture.md` y
  `doc/security.md` la normalización de ids, la herramienta nueva y la comprobación A5. En esta vuelta solo se escribe
  este plan.
- `deploy` y `qa-e2e`: sin cambios. La página no cambia.

## Decisiones que necesitan aprobación explícita

1. **«Palabra clave de la política de vacaciones»** (A2) se decide con `PolicyBook.match_question`: la regla aplica
   solo si el tema encontrado es `vacaciones`. «prima de vacaciones de EMP-0004» da tema `prima vacacional` y sigue
   en `rule:employee` (la prima no depende de la antigüedad en la política).
2. **Varios ids en la pregunta**: `rule:policy_employee` usa el primero. Calcular varios queda fuera de la adenda.
3. **Empleado de baja con menos de 1 año**: gana `status`; `days = 0` y la nota «El empleado no está activo.».
4. **«Hoy» es la fecha UTC de `clock.now()`.** Sin configuración nueva no hay zona horaria; el desfase posible es de
   horas alrededor del aniversario y queda en el ADR 0016.
5. **Formato inválido en `vacation_days`** (A3): no se llama a la herramienta, se registra `security`
   `control=tool_args` y el modelo recibe `{"error": "empleado no encontrado"}` (lo que pide la spec), no el mensaje
   genérico `argumento inválido para ...` de las otras herramientas.
6. **Números en A5 se comparan por valor sin ceros a la izquierda** para los datos de `vacation_days`: de `EMP-0004`
   se permiten `0004` y `4`; de `2022-01-10`, `2022`, `01`, `1` y `10`. También se permiten los números de `note`
   (son de código). Para los textos de política la comparación sigue como hoy (cadena completa; «5» no cuenta dentro
   de «15»).
7. **Gherkin con datos de prueba**: `SAMPLE_EMPLOYEES` no lleva acentos, así que los escenarios comprueban
   «Jorge Diaz»; «Jorge Díaz» con acento lo comprueba `test_contract_06.py` con los datos reales, como en la corrida 3.
8. **La frase de A5 es literal**, incluso «1 años» o «0 días»: la spec la fija y el contrato la usa.

## Módulos

Solo archivos de `product/app/` nuevos o cambiados.

- `employee_ids.py` (**nuevo**): `normalize_employee_ids(text)`, pura. Reemplaza «empleado 4», «empleado 004»,
  «empleado #4», «emp 4», «emp-4», «EMP4» (1 a 4 dígitos, sin importar mayúsculas, con límites de palabra y sin dígito
  pegado después) por `EMP-0004`. Idempotente: `EMP-0004` queda igual. «2021», «año 2021», «empleados 4» y «empresa 4»
  no cambian. `EMPLOYEE_ID_PATTERN` (`EMP-\d{4}`) vive aquí y lo reusan supervisor, reviewer y guardrails.
- `vacations.py` (**nuevo**): `years_of_service(start, today)` y `vacation_days_for(years)` puras (menos de 1 → 0;
  1 a 5 → `10 + 2*años`; 6 o más → `20 + 2*((años-1)//5)`). `VacationBook(directory, clock).vacation_days(employee_id)`
  devuelve exactamente `{"employee_id", "name", "start_date", "status", "years_of_service", "days", "note"}` o
  `{"error": "empleado no encontrado"}` (id inexistente o `start_date` ilegible). Usa `clock.now().date()`, nunca
  `datetime.now()`. Constantes de las dos notas de A3.
- `guard.py` (**cambia**): después de `redact_pii`, aplica `normalize_employee_ids` a la pregunta limpia. El historial
  no se normaliza. `GuardResult.summary()` agrega `ids_normalized` (conteo, sin texto).
- `supervisor.py` (**cambia**): `ROUTE_POLICY_EMPLOYEE = "rule:policy_employee"`. En `route_by_rules`, antes de
  `rule:employee`: id y tema `vacaciones` → `policy` con `topic="vacaciones"` y `employee_id` (el primero).
  `Decision` gana `employee_id: str | None`. Las demás reglas no cambian.
- `directory.py` (**cambia**): `find(employee_id) -> dict | None`, sin cambiar `get_employee`.
- `guardrails.py` (**cambia**): `TOOL_VACATION_DAYS = "vacation_days"`; `validate_tool_args` lo acepta solo con
  `employee_id` que cumpla `EMP-\d{4}` exacto (sin nombres).
- `agent.py` (**cambia**): `policy_tools(policies, vacations)` da `search_policy` y `vacation_days`; `directory_tools`
  no cambia (mínimo privilegio en los dos sentidos). `KNOWN_TOOLS` y `AUDITED_ARGS` suman `vacation_days`
  (`employee_id`). `prefetch` acepta una lista de `(herramienta, args)`, en orden, y sigue aceptando una tupla.
  `_call_tool`: para `vacation_days` con formato inválido devuelve `{"error": "empleado no encontrado"}` (decisión 5).
  `RunState.vacation_results` guarda los resultados con `days`; `result()` los pasa al orquestador (no llegan a `/ask`
  porque `main.py` filtra por `ASK_FIELDS` y `AGENT_FIELDS`).
- `orchestrator.py` (**cambia**): recibe `clock` y construye `VacationBook`. Con `rule:policy_employee`, `prefetch =
  [("search_policy", {"topic": "vacaciones"}), ("vacation_days", {"employee_id": id})]`. Pasa `vacation_results` al
  reviewer.
- `reviewer.py` (**cambia**): `ReviewInput.vacation_results`. `allowed_numbers(policy_texts, vacation_results)` y
  `vacation_sentence(result)` puras. En `policy`, si hay un número sin respaldo: con `vacation_results`, la frase de A5
  del primero (más `note` si no está vacía); sin ellos, la primera política o el mensaje fijo, como hoy. Sigue
  registrando `ungrounded` con `["policy_number"]` y pasa por el recorte.
- `prompts.py` (**cambia**): `POLICY_PROMPT` describe `vacation_days`, pide no negarse sin id (dar la regla completa y
  sugerir preguntar con `EMP-0004`) y, con un resultado de `vacation_days`, responder nombre, años, días y `note`.
- `llm.py` (**cambia**): `FakeModel` como `policy`: si hay un resultado de `vacation_days` con `days`, responde la frase
  de A5; si no, el `text` de la última política recibida; si no, como hoy. Reusa `vacation_sentence` de `reviewer.py`.
- `metrics.py` (**cambia**): `SUPERVISOR_ROUTES` suma `rule:policy_employee` (en 0 al inicio).
- `main.py` (**cambia**): pasa `clock` a `RequestPipeline`. Ninguna llave nueva en `/ask`.
- Sin cambios: el resto, incluido `tracing.py`, `clock.py`, `policies.py` y `static/index.html`.

## Flujo de una pregunta

Ejemplo: «¿Cuántos días de vacaciones tiene el empleado 004?».

1. La página manda `POST /ask` con `X-API-Key`; middleware, 401/429 y 422 como hoy.
2. Se abre el run raíz `request`.
3. **`agent.guard`**: inyección y PII; luego `normalize_employee_ids` deja «... tiene el EMP-0004?». Salida
   `{"pii_kinds": [], "injection": false, "ids_normalized": 1}`.
4. **`agent.supervisor`**: hay id y el tema es `vacaciones` → `policy`, `rule:policy_employee`, sin llamar al modelo.
5. Enrutador de costo: `route_question` elige el modelo del especialista, como hoy.
6. **`agent.policy`**: en código, `search_policy("vacaciones")` y `vacation_days("EMP-0004")` (dos runs de herramienta,
   dos `audit` `tool_call`, los dos en `tools_used`); sus resultados van con `TOOL_RESULT_PREFIX` antes de la pregunta.
   El modelo responde dentro de su bucle acotado.
7. **`agent.reviewer`**: secretos, PII y vacía; los números de la respuesta se comparan contra la política y el
   resultado de `vacation_days`; si sobra alguno, se usa la frase de A5; luego el recorte.
8. `agent_run` y `metrics` (`supervisor["rule:policy_employee"]` suma 1). Respuesta 200 con «Jorge Díaz (EMP-0004)
   tiene 4 años de servicio y le corresponden 18 días hábiles de vacaciones.» (reloj en 2026-11-19).

Sin id («¿Cuántos días de vacaciones tengo?»): `rule:policy`, solo `search_policy`, la respuesta trae la regla
completa («12 días hábiles»). Con «¿Quién es el empleado 4?»: `rule:employee` y `directory`, como siempre.

## Pruebas

Las escribe qa-unit antes que el código. `conftest.py`: `FakeClock` acepta `now` opcional (por omisión sigue
`FIXED_NOW`, que usa `test_logs.py`) y `build_harness` acepta `now`; constante `ADENDA_NOW = 2026-11-19 UTC`.
`SUPERVISOR_ROUTES_AT_ZERO` suma `rule:policy_employee`.

Pruebas viejas que se **actualizan** (la adenda cambia su supuesto; no es regresión):

- `test_supervisor.py::test_rules_apply_in_order...`: «¿EMP-0001 ya pidió sus vacaciones?» ahora es
  `rule:policy_employee`. Se cambia a «¿EMP-0001 ya cobró su aguinaldo?» para seguir probando `rule:employee` antes de
  `rule:policy`.
- `test_metrics.py` (y cualquier snapshot exacto de `supervisor`): suma la llave nueva en 0.
- `test_agent.py`: si fija la lista de herramientas de `policy`, ahora son `search_policy` y `vacation_days`.

Unitarias nuevas:

- `test_employee_ids.py`: cada forma de A1; ceros a la izquierda (`4`, `04`, `004`, `0004`); mayúsculas y minúsculas;
  idempotencia con `EMP-0004`; «2021», «año 2021», «empleados 4», «empresa 4» y «emp 12345» no cambian.
- `test_vacations.py` con reloj fijo: 0, 1, 4, 5, 6, 10 y 11 años (0, 12, 18, 20, 22, 22, 24); menos de 1 año con su
  nota; empleado de baja; id inexistente; formato inválido (`tool_args` registrado, herramienta no llamada,
  `{"error": "empleado no encontrado"}`); el día antes y el día del aniversario; las llaves exactas del resultado; no se
  usa `datetime.now()` (con el reloj fijo el resultado no depende de la fecha real).
- `test_supervisor.py` (se agrega): id y `vacaciones` → `rule:policy_employee` sin llamar al modelo; id y `prima de
  vacaciones` → `rule:employee` (decisión 1); id, departamento y vacaciones → `rule:policy_employee`; id escrito de
  otra forma llega normalizado.
- `test_reviewer.py` (se agrega): números de `vacation_days` pasan (días, años, `4` y `0004`, fecha); número inventado
  con `vacation_results` da la frase de A5 con `note`; sin `vacation_results` se comporta como hoy; un id escrito como
  «empleado 4» cuenta como escrito por la persona en `directory`.
- `test_specialists.py` (se agrega): `directory` no puede usar `vacation_days`; `policy` sí; con `rule:policy_employee`
  los dos `prefetch` van antes de la pregunta en ese orden, cuentan en `tools_used` y dejan dos `audit`.
- `test_llm.py` (se agrega): `FakeModel` como `policy` con resultado de `vacation_days` responde la frase de A5; con
  error de `vacation_days`, responde la política.
- `test_guard` (en `test_security.py` o archivo nuevo): la normalización ocurre después de ocultar PII y el resumen no
  lleva texto.

Gherkin, `tests/features/multiagent.feature` (escenarios nuevos con reloj en 2026-11-19):

- «¿Cuántos días de vacaciones tiene el empleado 004?» → `specialist = policy`, `supervisor_route =
  rule:policy_employee`, `tools_used` con `search_policy` y `vacation_days`, respuesta con «Jorge Diaz» y «18 días».
- «¿Cuántos días de vacaciones tiene EMP-0003?» → la respuesta dice «no está activo».
- «¿Cuántos días de vacaciones tengo?» → `rule:policy` y «12 días hábiles».
- Un especialista `policy` simulado que responde «Le tocan 40 días.» a la pregunta del empleado 004 → la respuesta no
  contiene «40» y es la frase de A5 con «18 días»; hay un `security` `ungrounded` con `["policy_number"]`.
- «¿Quién es el empleado 4?» → `specialist = directory`, `rule:employee`, «Jorge Diaz».

Concurrencia: `test_concurrency.py` agrega preguntas de vacaciones por empleado a la mezcla y comprueba el conteo de
`rule:policy_employee`. Traza: `test_root_trace.py` agrega que con `rule:policy_employee` los dos runs de herramienta
quedan dentro de `agent.policy`.

Fábrica: `verification unit` (cobertura de 80 % o más), `contract` (incluye las pruebas de la adenda en
`test_contract_06.py`), `qa`, `e2e` y `evaluate` (sin cambiar el set). Después de publicar: `verification production
<url>` y, en la página, las dos preguntas del hallazgo, revisando su traza en LangSmith.

## Riesgos

- **La normalización convierte números que no son ids** («emp» o «empleado» seguidos de un año, «empleado 2021») →
  se acepta por la spec (1 a 4 dígitos tras la palabra); «2021» suelto y «año 2021» no cambian, con prueba. Un id
  inexistente así (`EMP-2021`) cuenta como escrito por la persona y no dispara `ungrounded`, igual que hoy.
- **La normalización altera el texto que ve el modelo de `directory`** → es lo que pide A1; las pruebas viejas usan
  `EMP-dddd`, que no cambia (idempotente).
- **Pruebas viejas que asumían `rule:employee` con «vacaciones»** → se actualizan (ver Pruebas); qa-unit busca otros
  casos con id y palabra clave de vacaciones antes de entregar.
- **`FIXED_NOW` es 2026-01-02**: con él Jorge tendría 3 años y 16 días. Los escenarios usan `now` explícito y
  `FIXED_NOW` no se toca, para no romper `test_logs.py`.
- **El contrato usa `date.today()` local y el producto la fecha UTC** → difieren solo unas horas alrededor del
  10 de enero (aniversario de EMP-0004); queda documentado (decisión 4).
- **El modelo real escribe números de más** («a partir del 2.º año») → la respuesta se cambia por la frase de A5. Es
  seguro, no incorrecto; `POLICY_PROMPT` pide citar solo las cifras recibidas.
- **El modelo real sigue negándose sin id** (el hallazgo original) → A6 en el prompt y revisión manual en la página
  después de publicar; con `FakeModel` la respuesta es el texto de la política.
- **Datos personales en la traza**: el resultado de `vacation_days` trae nombre y fecha de ingreso en runs de
  herramienta y `llm` → `HIDE_INPUTS` y `HIDE_OUTPUTS` siguen obligatorios en producción; las etapas de código siguen
  sin texto y el resumen de `guard` solo agrega un conteo.
- **Mínimo privilegio**: `vacation_days` solo en el registro de `policy`; prueba en los dos sentidos. Sigue el riesgo
  conocido de la corrida 3: `policy` recibe el `Directory` completo, ahora también para `vacation_days`.
- **`datetime.now()` directo** → solo `SystemClock` lee el reloj; qa-style y una prueba con reloj fijo lo vigilan.
- **Bucles sin fin**: 2 correcciones en compuertas y 2 vueltas de qa-style; después se escala a una persona.

## Resumen

1. Alcance: solo la Adenda 1 (A1 a A7); los puntos 1 a 8 de la spec 06 ya están en producción y no se tocan.
2. `guard` normaliza «empleado 004», «emp-4», «EMP4» y similares a `EMP-0004`; el supervisor gana
   `rule:policy_employee` antes de `rule:employee` (id y tema `vacaciones`).
3. Herramienta nueva `vacation_days`, solo de `policy`, calculada en código con el reloj inyectado; con
   `rule:policy_employee` corre en código junto con `search_policy` antes del modelo.
4. El revisor permite también los números de `vacation_days` y, si sobra uno, responde la frase armada de A5.
5. Nuevos `employee_ids.py` y `vacations.py`; cambian `guard`, `supervisor`, `agent`, `orchestrator`, `reviewer`,
   `prompts`, `llm`, `guardrails`, `directory`, `metrics` y `main`. Se piden aprobar ocho decisiones.
