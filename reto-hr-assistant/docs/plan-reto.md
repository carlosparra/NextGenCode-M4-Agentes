# Plan · Reto: vacaciones, resumen por área y protección de PII (spec/05-reto.md)

Parte del producto de las sesiones 1 a 4, que sigue igual: clave, límite, compliance, trazas, métricas,
caché, contenedor, CI y Render. El enrutamiento cambia solo en cómo compara las palabras clave. Este plan solo
describe lo que cambia o se agrega. Plan aprobado por la persona con los comentarios integrados.

## Módulos

Archivos de `product/app/` (los nuevos o con cambios van marcados).

- `main.py` (cambia): `create_app()` y rutas; en `/ask` redacta la entrada, corre el agente, filtra la salida,
  emite `pii_detected` y agrega `pii_redacted` a la respuesta.
- `pii.py` (nuevo): detector con expresiones regulares (EMAIL, CARD con Luhn, CURP, RFC, PHONE) y `redact(text)`
  que devuelve el texto con marcadores y los tipos encontrados, nunca los valores.
- `output_filter.py` (nuevo): `clean_answer(text, max_chars, redactor)`: quita etiquetas HTML, redacta PII,
  recorta a `MAX_ANSWER_CHARS` y, si queda vacía, devuelve «No tengo una respuesta para eso.»
- `directory.py` (cambia): listas de campos permitidos por herramienta, `get_vacation_balance`,
  `department_summary` y comparación de departamento sin mayúsculas ni acentos (`unicodedata`).
- `agent.py` (cambia): registra las cuatro herramientas con sus argumentos; el prompt del sistema las describe en una
  línea cada una.
- `llm.py` (cambia): el `FakeModel` agrega dos reglas, antes de las existentes: id + «vacaciones» pide
  `get_vacation_balance`; «resumen» + departamento pide `department_summary`.
- `routing.py` (cambia, lo implementa security): las palabras clave se comparan como palabras completas sobre el
  texto normalizado (límites de palabra), para que «resumen» no active «resume»; así las preguntas de
  `department_summary` van al modelo chico, porque el cálculo lo hace el código.
- `config.py` (cambia): `PII_REDACTION` (booleano, `true`) y `MAX_ANSWER_CHARS` (entero positivo, `1500`).
- `compliance.py` (cambia): `_pii_violations`: en producción, `PII_REDACTION` debe valer `true`.
- `metrics.py` (cambia): `record_pii(direction, types)` y `pii_detections` en `snapshot()`, siempre con las llaves
  `input` y `output`.
- `static/index.html` (cambia, aprobado): pinta el turno de la persona solo después de un `200`; si `pii_redacted`
  no está vacío, en lugar del texto muestra «Tu pregunta tenía datos personales que se ocultaron: EMAIL».
- Sin cambios: `logs.py`, `middleware.py`, `security.py`, `gateway.py`, `pricing.py`, `tracing.py`, `clock.py`,
  `model_reply.py`.

Fuera de `app/`: `data/employees.json` se vuelve a copiar de `spec/employees.json` (developer); `README.md`,
`.env.example` y `doc/compliance-checklist.md` los actualiza security. deploy corre en paralelo en el paso 4 y agrega
`PII_REDACTION=true` a `render.yaml`. `verification/eval_set.json` ya trae las tres preguntas nuevas y `evaluate.py`
ya soporta `must_not_include`: nadie escribe ahí.

## Flujo de una pregunta

1. La página manda `POST /ask` con `question`, `history` y `X-API-Key`.
2. El middleware asigna `request_id`; seguridad valida la clave (401) y el límite (429); Pydantic valida el cuerpo
   (422).
3. Si `PII_REDACTION=true`, `pii.redact` se aplica a la pregunta y a cada turno del historial. Los tipos de la
   pregunta forman `pii_redacted`; si hay alguno se emite `pii_detected` con `direction: "input"` y se suma a las
   métricas (uno por tipo por evento). Desde aquí nadie ve el texto original.
4. El enrutador elige el modelo con la pregunta ya redactada, comparando palabras clave completas, y se recorta el
   historial a `HISTORY_WINDOW`.
5. El agente corre dentro de `request_scope` (traza) con la pregunta redactada. Cada herramienta emite `audit`
   igual que antes y devuelve solo sus campos permitidos, con los números ya calculados en código.
6. `output_filter.clean_answer` toma la respuesta del modelo: quita HTML, redacta PII (si hay, `pii_detected` con
   `direction: "output"` y métricas), recorta a `MAX_ANSWER_CHARS` y aplica el texto de respaldo si quedó vacía.
7. Se calcula el costo, se emite `agent_run` (solo números) y se responde `200` con los campos de siempre más
   `pii_redacted`.
8. La página pinta la respuesta con `textContent`, y el turno de la persona según el punto de `index.html`.

## Pruebas

Escenarios Gherkin (qa-unit, `tests/features/`):

- `tools.feature` (nuevo): saldo de un empleado activo (EMP-0004 muestra días disponibles = total - tomados);
  empleado de `baja` sin saldo; id inexistente con el mismo mensaje que `get_employee`; resumen de «Ventas», de
  «tecnologia» (sin acento) y de un departamento inexistente que lista los válidos; ninguna herramienta devuelve
  `personal_email` ni `personal_phone`.
- `pii.feature` (nuevo): pregunta con correo responde `200` con `pii_redacted: ["EMAIL"]` y el modelo, el log y la
  respuesta no contienen el valor; pregunta sin PII da lista vacía; `EMP-0001` no es PII; respuesta del modelo con
  teléfono sale con `[PHONE]`; respuesta con HTML sale sin etiquetas; respuesta vacía tras el filtro da el texto de
  respaldo; `/metrics` cuenta por dirección y tipo.
- `compliance.feature` (cambia): ejemplo nuevo `PII_REDACTION = false` en producción no arranca.

Pruebas unitarias:

- `test_pii.py`: un positivo y un negativo por tipo; teléfono con espacios, guiones y `+52`; tarjeta que pasa y que
  no pasa Luhn; CURP no se reporta además como RFC; fechas `2019-03-04` y ids `EMP-0000` no son PII; los tipos salen
  sin duplicados y nunca con valores.
- `test_output_filter.py`: HTML que parte un correo (`ana<b>@</b>x.com`) se detecta; recorte exacto a
  `MAX_ANSWER_CHARS`; orden HTML -> PII -> recorte; respaldo con texto vacío o solo etiquetas; con
  `PII_REDACTION=false` no se redacta, pero el HTML y el recorte se aplican.
- `test_directory.py`: listas de campos permitidos (un campo nuevo en los datos no aparece); cálculo de disponibles;
  promedio con un decimal solo de activos; departamento sin activos da promedio `null`.
- `test_routing.py` (qa-unit): «Dame el resumen del departamento de Ventas» va a `MODEL_SMALL` con `default_small`;
  «resume las altas» sigue yendo al grande con `keyword:resume`; «por qué» y las demás palabras clave siguen igual.
- `test_llm.py`: las dos reglas nuevas del `FakeModel` y que las cuatro anteriores siguen igual.
- `test_agent.py`: el prompt nombra las cuatro herramientas; argumentos incorrectos de las nuevas dan `Error:`.
- `test_config.py`, `test_metrics.py`/`test_observability.py`, `test_main.py`: variables nuevas e inválidas,
  `pii_detections` (dos correos en la misma pregunta cuentan `EMAIL: 1`), `pii_redacted` y un modelo espía que
  comprueba que nunca recibe el valor original (pregunta e historial).

E2E (qa-e2e): saldo de EMP-0004 muestra un número; la pregunta con `ana@example.com` responde y la página nunca
muestra ese texto.

## Riesgos

- **Fuga por `get_employee`**: hoy devuelve el registro completo; con los datos nuevos saldrían `personal_email` y
  `personal_phone`. Se evita con listas de campos permitidos (ADR 0014) y una prueba que busca esos campos en cada
  herramienta.
- **La página repite la pregunta**: hoy pinta el texto de la persona antes de la respuesta, y el e2e del correo
  fallaría. Se evita pintando el turno tras el `200` con el aviso de datos ocultos (cambio aprobado por la persona).
- **El historial trae PII**: el navegador reenvía la pregunta original en `history`. Se redacta también; no emite
  evento ni métricas para no contar dos veces el mismo dato.
- **Orden del FakeModel**: «¿Cuántos días... EMP-0004?» tiene un id y caería en `get_employee`; «resumen ... Ventas»
  caería en `search_by_department`. Las reglas nuevas van antes.
- **Falsos positivos y solapes**: CURP contiene la forma de un RFC, una tarjeta que no pasa Luhn podría verse como
  teléfono, y dos fechas seguidas suman diez dígitos. Orden fijo (EMAIL, CARD, CURP, RFC, PHONE), límites de dígito
  con lookarounds y pruebas de cada caso (ADR 0013).
- **Recortar antes de redactar** dejaría medio correo sin detectar; quitar HTML después también. El orden queda fijo
  en ADR 0015.
- **Costo**: el prompt crece con dos herramientas; se mantiene una línea por herramienta. Con la comparación por
  palabra completa, «resumen» ya no activa «resume» y las preguntas de `department_summary` van al modelo chico, lo
  que baja el costo por respuesta frente a la sesión 3; `test_routing.py` lo fija. El riesgo nuevo es que formas
  derivadas que antes coincidían por subcadena («explícame», «analizar», «comparación») ahora vayan al chico: se
  aceptan porque el cálculo lo hace el código, y `evaluate` compara calidad y costo contra la línea base con el
  mismo prompt; si la calidad baja, se agregan esas formas a la lista.
- **El valor detectado llega al log por accidente** (en un mensaje de error o en `args`): `pii.py` nunca guarda
  valores, el evento solo lleva tipos y una prueba revisa el flujo de log completo.

Decisiones tomadas por la persona: (1) el conteo de `pii_detections` es uno por tipo por evento, igual que `types`,
no por ocurrencia; (2) sin activos, el promedio de `department_summary` es `null`; (3) con `PII_REDACTION=false` no se
detecta ni se redacta, pero el HTML y el recorte se aplican siempre.
