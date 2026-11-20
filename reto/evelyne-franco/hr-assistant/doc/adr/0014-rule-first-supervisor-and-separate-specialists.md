# ADR 0014: Supervisor con reglas antes que modelo y especialistas con herramientas separadas

## Contexto

Hasta el reto de seguridad (ADR 0013) había un solo agente con `get_employee` y `search_by_department`. La spec 06
agrega preguntas sobre políticas de RH (`data/policies.json`: vacaciones, prima vacacional, aguinaldo, home office,
permisos, horario). Hace falta decidir quién contesta cada pregunta sin subir el costo ni la latencia, sin perder
determinismo en las pruebas y sin darle a un agente más herramientas de las que necesita. Un modelo que contesta
políticas de memoria puede inventar números (días, porcentajes).

Adenda 1 (hallazgo de producción): «¿Cuántos días de vacaciones tiene el empleado 004?» respondía el texto completo
de la política sin decir cuántos días le tocan. «empleado 004» no se reconocía como `EMP-0004`, con un id la regla
`rule:employee` mandaba la pregunta a `directory`, y `policy` no tenía la fecha de ingreso ni quién calculara la
antigüedad.

## Decisión

- **Orquestador:** `app/orchestrator.py:RequestPipeline.run` corre, en este orden, `guard` (`app/guard.py`),
  `supervisor` (`app/supervisor.py`), **un** especialista y `reviewer` (`app/reviewer.py`). Cada etapa lee y escribe
  un `RequestContext` local de la petición; nada se comparte entre peticiones.
- **Supervisor, reglas primero:** `route_by_rules` aplica, sin modelo y sobre el texto ya limpio, en este orden: id
  `EMP-dddd` con el tema `vacaciones` (`rule:policy_employee`, Adenda 1), id `EMP-dddd` (`rule:employee`),
  departamento del directorio con `fold_text` y límites de palabra (`rule:department`), palabra clave de política
  (`rule:policy`, con `PolicyBook.match_question`; gana la palabra clave más larga). Si ninguna aplica,
  `Supervisor.decide` hace **una** llamada a `MODEL_SMALL` con `SUPERVISOR_PROMPT` y la pregunta, sin historial:
  respuesta válida da `model`; cualquier otra, `directory` con `model_invalid`. Si el modelo falla, sube
  `ModelUnavailable` y la API responde `502`, como antes.
- **Costo:** la llamada del supervisor viaja como `Seed` al especialista y `RunState.add` la suma a `input_tokens`,
  `output_tokens` y `cost_usd` con el precio de `MODEL_SMALL` (gratis si vino de caché). El enrutador de costo de la
  sesión 3 (`route_question`) sigue eligiendo solo el modelo **del especialista**.
- **Especialistas separados:** los dos son instancias de `app/agent.py:Agent` con su propio registro de
  herramientas: `directory_tools` (`get_employee`, `search_by_department`) y `policy_tools` (`search_policy` y, desde
  la Adenda 1, `vacation_days`, con `POLICY_PROMPT`). Una herramienta ajena se trata como `unknown_tool` en
  `Agent._call_tool`, no se ejecuta y deja `security` con `control=tool_args`.
- **Política consultada en código:** con `rule:policy`, el orquestador pasa `prefetch` con `search_policy` del tema
  y el especialista ejecuta la herramienta antes de la pregunta (`Agent._start_messages`), con su `audit` y su lugar
  en `tools_used`. El `reviewer` comprueba los números de la respuesta contra los textos consultados.

### Adenda 1: vacaciones por empleado, calculadas en código

- **Ids escritos de otra forma:** `app/employee_ids.py:normalize_with_count` convierte «empleado 4», «empleado #4»,
  «emp 4», «emp-4» y «EMP4» (1 a 4 dígitos, sin importar mayúsculas) en `EMP-0004`. Lo llama `screen_input` sobre la
  pregunta ya limpia de PII; el historial no se toca. `GuardResult.summary` solo reporta `ids_normalized` (un
  conteo). Un número sin «empleado» o «emp» (por ejemplo «2021») no es un id.
- **Regla `rule:policy_employee`:** si la pregunta trae un `EMP-dddd` y `match_question` devuelve el tema
  `vacaciones`, va a `policy` con el primer id (`Decision.employee_id`). Si gana otro tema (por ejemplo «prima
  vacacional»), la regla no aplica y sigue `rule:employee`. `/metrics` la cuenta en `supervisor`.
- **Herramienta `vacation_days`:** `app/vacations.py:VacationBook`, de solo lectura sobre el `Directory`, con el
  reloj inyectado (`create_app` pasa el mismo `clock` al `RequestPipeline`). Devuelve solo `employee_id`, `name`,
  `start_date`, `status`, `years_of_service`, `days` y `note`; la tabla de días está en `vacation_days_for`.
- **Consulta en código:** con `rule:policy_employee`, `RequestPipeline._prefetch` pasa `search_policy("vacaciones")`
  y `vacation_days(<id>)`, en ese orden; las dos dejan `audit` y cuentan en `tools_used`.
- **Revisor:** los números de los resultados de `vacation_days` también valen (por valor, sin ceros a la izquierda).
  Si hay un número sin respaldo y hubo `vacation_days`, la respuesta se cambia por `vacation_sentence` (frase armada
  en código con el resultado y su `note`); si no, por el texto de la política, como antes.
- No se escribió un ADR aparte: la Adenda 1 extiende el mismo supervisor y el mismo especialista `policy`.

## Consecuencias

- La mayoría de las preguntas se enrutan gratis, en microsegundos y siempre igual; las pruebas cuentan llamadas con
  un modelo espía (`tests/test_supervisor.py`).
- Solo las preguntas sin regla pagan una llamada extra a `MODEL_SMALL`; se ve en `supervisor_route = model` y en
  `GET /metrics` (`supervisor`).
- Las reglas tienen falsos positivos: una pregunta de directorio que contiene «horario» o «permisos» va a `policy`
  si no trae id ni departamento. El orden de las reglas reduce ese caso. Con la Adenda 1, una pregunta de directorio
  con id que menciona «vacaciones» («¿EMP-0004 está de vacaciones?») va a `policy` y recibe el cálculo de días.
- El mínimo privilegio está en el registro de herramientas, no en el acceso a objetos: el especialista `policy`
  recibe el `Directory` para validar argumentos y, desde la Adenda 1, `VacationBook` lo lee para calcular días.
  `directory` no tiene `vacation_days`. Agregar una herramienta exige decidir a qué registro va.
- Con `rule:policy` y `rule:policy_employee` el modelo siempre tiene los datos enfrente y el cálculo de antigüedad
  nunca lo hace el modelo; con `model` el especialista `policy` debe pedir las herramientas por sí mismo y, si no lo
  hace, el `reviewer` responde el mensaje fijo cuando hay números.
- La normalización de ids cambia lo que ven el supervisor, el especialista y el revisor: un id escrito de otra forma
  cuenta como escrito por la persona en la comprobación contra el directorio.
- Los campos y llaves anteriores no cambian; solo se agregan `specialist`, `agents` y `supervisor_route` en `/ask`
  y `specialists` y `supervisor` en `/metrics` (con el motivo nuevo `rule:policy_employee`).
