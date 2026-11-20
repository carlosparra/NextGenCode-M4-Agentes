# Reto · Multi-agente en producción y traza raíz por petición

Parte del producto del reto (`spec/05-security-hardening.md`), que ya está publicado en Render. Hoy el producto tiene
**un solo agente** con dos herramientas. Esta spec lo convierte en un **sistema multi-agente en tiempo de ejecución**
y cierra la brecha de observabilidad encontrada en producción: la detección de PII en la entrada no aparecía en
LangSmith porque ocurría antes de que empezara la traza `agent_run`.

**Nada de lo que ya funciona puede romperse.** Las pruebas y verificaciones de las sesiones 1 a 4 y de la spec 05
siguen pasando. Los campos de `/ask` y las llaves de `/metrics` que ya existen no cambian de nombre ni de significado.

## Los agentes de cada petición

Cada `POST /ask` pasa por estos agentes, **en este orden**:

| Agente | Tipo | Qué hace |
| --- | --- | --- |
| `guard` | Código | El filtro de entrada de la spec 05 (PII, inyección, auditoría), sin cambios de comportamiento |
| `supervisor` | Reglas y, si no alcanzan, el modelo chico | Elige qué especialista contesta |
| `directory` | Especialista (agente con bucle acotado) | El agente actual, con `get_employee` y `search_by_department` |
| `policy` | Especialista nuevo (agente con bucle acotado) | Contesta sobre políticas de RH con `search_policy` |
| `reviewer` | Código | La validación de salida de la spec 05 más la comprobación contra los datos (punto 4) |

Solo corre **un** especialista por petición.

## Lo que debe hacer

1. **Supervisor.**
   - Primero intenta con **reglas en código, sin llamar al modelo**, en este orden:
     1. La pregunta trae un id `EMP-dddd` → `directory`, motivo `rule:employee`.
     2. La pregunta nombra un departamento que existe en el directorio (sin acentos ni mayúsculas, con `fold_text`)
        → `directory`, motivo `rule:department`.
     3. La pregunta trae una palabra clave de una política de `data/policies.json` (sin acentos ni mayúsculas) →
        `policy`, motivo `rule:policy`.
   - Si ninguna regla aplica, hace **una** llamada a `MODEL_SMALL`, sin historial, con un prompt de clasificación que
     debe responder `{"specialist": "directory"}` o `{"specialist": "policy"}`. Motivo `model`. Si la respuesta no es
     válida, usa `directory` con motivo `model_invalid`. Esa llamada **suma** a `input_tokens`, `output_tokens` y
     `cost_usd` de la petición.
   - El supervisor solo ve el texto que ya limpió `guard`.
   - El enrutador de costo de la sesión 3 (`ROUTING`, campo `route`) sigue eligiendo el modelo **del especialista**.
     Son dos decisiones distintas: `supervisor_route` dice qué especialista contesta, `route` dice con qué modelo.
2. **Especialista `policy`.**
   - Nuevo archivo `data/policies.json`, copia de `spec/policies.json`: una lista de políticas, cada una con `topic`,
     `keywords` y `text`.
   - Herramienta `search_policy(topic)`, de solo lectura. Busca el tema sin acentos ni mayúsculas, por `topic` o por
     cualquiera de sus `keywords`. Si lo encuentra, devuelve `{"topic": ..., "text": ...}`. Si no, devuelve
     `{"error": "tema no encontrado", "topics": [...]}` con la lista de temas disponibles.
   - Su argumento se valida como en la spec 05 punto 4: texto de 1 a 60 caracteres. Uno inválido no llama a la
     herramienta y registra `security` con `control=tool_args`.
   - Tiene su propio prompt de sistema y su propio bucle con tope (`AGENT_MAX_STEPS`). No tiene acceso a
     `get_employee` ni a `search_by_department`, y `directory` no tiene acceso a `search_policy` (mínimo privilegio).
   - **La política se consulta en código.** Con `supervisor_route = rule:policy`, antes de llamar al modelo el
     producto ejecuta `search_policy` con el tema encontrado y pone el resultado como resultado de herramienta
     (`TOOL_RESULT_PREFIX`) antes de la pregunta. Así el modelo no decide si la consulta: siempre la tiene enfrente.
     Esa consulta cuenta en `tools_used` y deja su evento `audit` `tool_call`.
3. **Modelo simulado.** `FakeModel` sabe hacer los dos papeles nuevos, sin red:
   - Como supervisor: si el último mensaje trae una palabra clave de política responde `{"specialist": "policy"}`; si
     no, `{"specialist": "directory"}`.
   - Como especialista `policy`: si recibe un resultado de herramienta, responde con ese texto; si el último mensaje
     trae una palabra clave de política, pide `search_policy` con ese tema.
   - Sus reglas actuales del especialista `directory` no cambian.
4. **Revisor (comprobación contra los datos).** Después de la validación de salida de la spec 05 (secretos → PII →
   vacía) y **antes** del recorte:
   - Respuesta de `directory`: si cita un id `EMP-dddd` que **no existe** en el directorio y que la persona **no
     escribió** en su pregunta, la respuesta se reemplaza por «No pude verificar la respuesta con el directorio.
     Intenta de nuevo.». Un id inexistente que la persona sí escribió puede aparecer (la respuesta puede decir «no
     existe»).
   - Respuesta de `policy`: cada número de la respuesta (`\d+`, completo: «5» no cuenta dentro de «15») debe aparecer
     en el texto de alguna política consultada en esa petición. Si alguno no aparece, la respuesta se reemplaza por el
     texto de la primera política consultada; si no se consultó ninguna, por «No pude verificar la respuesta con las
     políticas. Intenta de nuevo.».
   - Cada reemplazo registra `security` con `stage=output`, `control=ungrounded` y `kinds` igual a
     `["employee_id"]` o `["policy_number"]`. Nunca el valor.
5. **Respuesta de `/ask`.** Agrega, sin cambiar los campos que ya existen:
   - `specialist`: `directory` o `policy`.
   - `agents`: los agentes que corrieron, en orden. Por ejemplo `["guard", "supervisor", "policy", "reviewer"]`.
   - `supervisor_route`: `rule:employee`, `rule:department`, `rule:policy`, `model` o `model_invalid`.
6. **Traza raíz por petición** (brecha de observabilidad de producción).
   - Cada `POST /ask` abre **un solo run raíz** `request` (tipo `chain`) en LangSmith. Todo lo demás de la petición
     queda **dentro** de él, como hijos, en este orden: `agent.guard`, `agent.supervisor`, el especialista
     (`agent.directory` o `agent.policy`, con sus runs `llm` y de herramienta adentro) y `agent.reviewer`.
   - Los spans `security` de la **entrada** quedan dentro de `agent.guard`, y los de la salida dentro de
     `agent.reviewer`.
   - La llamada al modelo del supervisor (cuando la hay) es un run `llm` dentro de `agent.supervisor`.
   - Los metadatos de **todos** los runs llevan `request_id` y `client`; el raíz y el del especialista llevan además
     `specialist` y `supervisor_route`. Nunca la clave.
   - Los runs raíz, `agent.guard`, `agent.supervisor` y `agent.reviewer` **no reciben el texto como argumento**: la
     función trazada no tiene parámetros de texto y su salida es un resumen con tipos, conteos y decisiones (por
     ejemplo `{"pii_kinds": ["email"], "injection": false}` o `{"specialist": "policy", "route": "rule:policy"}`).
     Así no dependen solo de `HIDE_INPUTS` y `HIDE_OUTPUTS`, que siguen obligatorios en producción.
   - Con las trazas apagadas (`LANGSMITH_TRACING=false`) no se importa `langsmith`, como hoy.
7. **Log y métricas.**
   - El evento `agent_run` agrega `specialist` y `supervisor_route`. Sigue sin texto.
   - `GET /metrics` agrega `specialists`, un conteo por especialista (`{"directory": 3, "policy": 1}`), y
     `supervisor`, un conteo por motivo (`{"rule:employee": 2, "model": 1, ...}`). Las llaves que ya existen no
     cambian.
8. **Documentación.**
   - `product/doc/architecture.md`: diagrama de los agentes de una petición y de la traza raíz.
   - Un ADR nuevo para el supervisor con reglas antes que modelo y los especialistas con herramientas separadas, y
     otro para la traza raíz por petición.
   - `product/doc/security.md`: agregar la comprobación contra los datos (punto 4) y el mínimo privilegio entre
     especialistas.
   - `product/README.md`: la sección de arquitectura y los campos nuevos de `/ask` y `/metrics`.

## Configuración nueva

Ninguna. Se reusan `MODEL_SMALL`, `AGENT_MAX_STEPS` y `MAX_ANSWER_CHARS`.

## Cómo se comprueba

- Pruebas unitarias del supervisor: cada regla, el orden entre reglas, la llamada al modelo cuando ninguna aplica
  (con un modelo espía que cuenta llamadas), la respuesta inválida (`model_invalid`) y que las reglas no llaman al
  modelo.
- Pruebas de `search_policy`: tema por `topic`, por palabra clave sin acentos, tema inexistente y argumento inválido.
- Pruebas del revisor: id inventado reemplazado; id inexistente escrito por la persona no se reemplaza; número que
  no está en la política reemplazado por la política; números de la política pasan; sin política consultada da el
  mensaje fijo; la respuesta de `directory` no se compara contra políticas.
- Escenarios Gherkin:
  - «¿Cuántos días de vacaciones tengo?» responde `200` con `specialist = policy`, `supervisor_route = rule:policy`,
    `agents = ["guard", "supervisor", "policy", "reviewer"]` y el número de días de la política.
  - «¿De cuánto es el aguinaldo?» con un especialista `policy` simulado que contesta un número que no está en la
    política: la respuesta final no contiene ese número y sí contiene el texto de la política de aguinaldo.
  - «¿Quién es EMP-0004?» sigue respondiendo con «Jorge Díaz» y `specialist = directory`.
- Prueba de la traza raíz con un trazador espía: una sola raíz `request` por petición; `agent.guard`,
  `agent.supervisor`, el especialista y `agent.reviewer` son hijos de esa raíz y en ese orden; un span `security` de
  entrada (pregunta con correo) queda dentro de `agent.guard`; los runs raíz, `agent.guard`, `agent.supervisor` y
  `agent.reviewer` se llaman sin argumentos de texto y su salida no contiene la pregunta.
- La prueba de concurrencia de la spec 05 sigue pasando, con preguntas de los dos especialistas mezcladas.
- `verification unit`, `contract` (incluye `test_contract_06.py`), `qa`, `e2e` y `evaluate` siguen pasando, con
  cobertura de 80 % o más. El set de `evaluate` no cambia.
- Después de publicar: `uv run python -m verification production <url>` y una pregunta de políticas en la página.

## Adenda 1 · Vacaciones por empleado (hallazgo de producción)

**Qué pasó.** Con el sistema ya publicado, en la página:
- «¿Cuántos días de vacaciones tengo?» → el especialista `policy` tenía la política enfrente, pero el modelo respondió
  que no conocía la antigüedad de la persona y no dio la regla.
- «¿Cuántos días de vacaciones tiene el empleado 004?» → respondió el texto completo de la política, sin decir cuántos
  días le tocan a ese empleado.

Causas: «empleado 004» no se reconoce como `EMP-0004`; con un id la regla `rule:employee` manda la pregunta a
`directory`, que no sabe de políticas; y `policy` no tiene la fecha de ingreso ni quién calcule la antigüedad. El
cálculo **no** se le deja al modelo: se hace en código, igual que la consulta de la política.

**Lo que debe hacer.**

A1. **Ids escritos de otra forma.** Además de `EMP-dddd`, se reconoce como id de empleado, sin importar mayúsculas:
    «empleado 4», «empleado 004», «empleado #4», «emp 4», «emp-4» y «EMP4» (de 1 a 4 dígitos, con ceros a la
    izquierda o sin ellos) → `EMP-0004`. La normalización la hace `guard` sobre el texto ya limpio de PII, así la ven
    el supervisor, el especialista y el revisor (un id que la persona escribió de otra forma cuenta como escrito por la
    persona en el punto 4). Un número suelto sin la palabra «empleado» o «emp» (por ejemplo «2021») no es un id.
A2. **Supervisor.** Nueva regla, **antes** de `rule:employee`: si la pregunta trae un id **y** una palabra clave de la
    política de vacaciones → `policy`, motivo `rule:policy_employee`. Las demás reglas no cambian. `/metrics` la cuenta
    en `supervisor` como cualquier otro motivo.
A3. **Herramienta `vacation_days(employee_id)`**, solo del especialista `policy`, de solo lectura. Usa el reloj
    inyectado del producto (`app/clock.py`), nunca `datetime.now()` directo. Devuelve solo:
    `{"employee_id", "name", "start_date", "status", "years_of_service", "days", "note"}`.
    - `years_of_service`: años completos desde `start_date` hasta hoy.
    - `days`, según la política de vacaciones: 1 año → 12; 2 → 14; 3 → 16; 4 → 18; 5 → 20; de 6 a 10 → 22; de 11 a
      15 → 24; y así, 2 días más por cada 5 años.
    - Con menos de 1 año: `days = 0` y `note` = «Aún no cumple su primer año; al cumplirlo le corresponden 12 días
      hábiles.».
    - Con `status` distinto de `activo`: `days = 0` y `note` = «El empleado no está activo.».
    - En los demás casos `note` es una cadena vacía.
    - Id inválido o inexistente: `{"error": "empleado no encontrado"}`, con la misma validación de argumentos de la spec
      05 punto 4 (`security` con `control=tool_args` si el formato es inválido).
A4. **Consulta en código.** Con `rule:policy_employee`, antes de llamar al modelo el producto ejecuta
    `search_policy("vacaciones")` y `vacation_days(<id>)` y pone los dos resultados como resultados de herramienta.
    Las dos cuentan en `tools_used` y dejan su `audit` `tool_call`.
A5. **Revisor.** En una respuesta de `policy`, los números permitidos son los de las políticas consultadas **y** los de
    los resultados de `vacation_days` de esa petición (días, años, fecha de ingreso, id). Si el modelo escribe un número
    que no está en ninguno, la respuesta se reemplaza por una respuesta armada en código con el resultado de
    `vacation_days`: «<name> (<employee_id>) tiene <years_of_service> años de servicio y le corresponden <days> días
    hábiles de vacaciones.», seguida de `note` si no está vacía. Si no hubo `vacation_days`, se reemplaza por el texto
    de la política, como hoy.
A6. **Prompt de `policy`.** Si la respuesta depende de datos de la persona y no hay un id de empleado, no se niega:
    responde con la regla completa de la política y sugiere preguntar con el id (por ejemplo `EMP-0004`). Si recibe un
    resultado de `vacation_days`, responde con el nombre, los años de servicio y los días, y la `note` si la hay.
A7. **Modelo simulado.** Como especialista `policy`, si recibe un resultado de `vacation_days` responde con la frase de
    A5 armada con ese resultado.

**Cómo se comprueba.**
- Pruebas unitarias de la normalización de ids: cada forma de A1, ceros a la izquierda, mayúsculas, y que «2021» o
  «año 2021» no se conviertan en id.
- Pruebas unitarias de `vacation_days` con un reloj fijo: 0, 1, 4, 5, 6, 10 y 11 años; menos de 1 año; empleado de
  baja; id inexistente; id con formato inválido.
- Escenarios Gherkin con reloj fijo en 2026-11-19:
  - «¿Cuántos días de vacaciones tiene el empleado 004?» → `specialist = policy`,
    `supervisor_route = rule:policy_employee`, `tools_used` contiene `search_policy` y `vacation_days`, y la respuesta
    contiene «Jorge Díaz» y «18 días».
  - «¿Cuántos días de vacaciones tiene EMP-0003?» → la respuesta dice que no está activa.
  - «¿Cuántos días de vacaciones tengo?» → `rule:policy` y la respuesta contiene «12 días hábiles».
  - Un especialista simulado que responde «Le tocan 40 días.» a la pregunta del empleado 004 → la respuesta final no
    contiene «40» y es la frase armada de A5 con «18 días».
- «¿Quién es el empleado 4?» → `specialist = directory`, `supervisor_route = rule:employee` y «Jorge Díaz».
- `verification contract` incluye las pruebas nuevas de `test_contract_06.py`. El set de `evaluate` no cambia.
