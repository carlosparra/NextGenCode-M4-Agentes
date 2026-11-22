# Plan del HR Assistant (sesión 4: producción)

Parte del producto de las sesiones 1 a 3, que sigue igual. Se agrega acceso por clave, límite de peticiones, compliance como código, contenedor, pipeline de CI y Blueprint de Render. `product/` es la raíz del repositorio que publica `scripts/publish.py`.

## Módulos

Todos en `product/app/` salvo indicación. Nuevos marcados con (nuevo); cambiados con (cambia).

- `config.py` (cambia): agrega `environment` (`development` por omisión; solo `development` o `production`), `api_keys` (`API_KEYS`, diccionario `cliente -> clave`, con `repr=False`) y `rate_limit_per_minute` (30, entero mayor que cero). `API_KEYS` mal formada impide arrancar con un error que dice la entrada (posición) y su largo, nunca su valor.
- `security.py` (nuevo): `parse_api_keys(raw)` (forma `cliente:clave,cliente2:clave2`; entrada sin `:`, cliente o clave vacíos, cliente repetido son errores sin valor), `authenticate(api_keys, received)` que devuelve el nombre del cliente o `None`, comparando con `hmac.compare_digest` contra todas las claves (sin cortar al primer acierto), y `RateLimiter(limit, clock)`: ventana fija de un minuto por cliente, devuelve los segundos que faltan (`Retry-After`) si se pasa. Sin estado fuera del proceso.
- `compliance.py` (nuevo): `check_production(settings)` devuelve la lista de reglas violadas; `create_app` la usa y lanza `ValueError` si `ENVIRONMENT=production` y falla cualquiera: `MODEL_PROVIDER=fake`, `API_KEYS` vacía o clave de menos de 16 caracteres, trazas encendidas con `HIDE_INPUTS` o `HIDE_OUTPUTS` distinto de `true`. Los mensajes nombran la regla y el cliente, nunca la clave.
- `main.py` (cambia): una dependencia de FastAPI `require_client` en `POST /ask` y `GET /metrics`: lee `X-API-Key`, autentica, aplica el límite y guarda el cliente en un `ContextVar`. `401 {"detail": "invalid or missing API key"}` o `429 {"detail": "rate limit exceeded"}` con `Retry-After`. `/`, `/health` y `/docs` quedan libres. `create_app()` recibe además `limiter` opcional (y usa el `clock` ya inyectado). Llama a `compliance` al construir.
- `observability.py` (cambia poco): el logger agrega `client` a cada evento cuando hay cliente en el contexto (incluye `request`, `audit`, `agent_run`, `error`); sin cliente, el campo no aparece. Nunca recibe la clave.
- `agent.py` (cambia poco): `audit` y `agent_run` ya salen por el logger y heredan `client`; no cambia su lógica. Las trazas reciben `client` como metadato (no la clave) por `tracing.py`.
- `tracing.py` (cambia poco): acepta metadatos y manda `client`; con `hide_inputs` y `hide_outputs` sigue sin mandar contenido.
- `static/index.html` (cambia): campo `data-testid="api-key"` tipo contraseña; la clave vive en `sessionStorage` (nunca `localStorage` ni en el código) y se manda en `X-API-Key`. `401` muestra «Clave inválida»; `429` muestra «Demasiadas preguntas; espera N segundos» con `Retry-After`. Conserva `question`, `send` y `answer`. Todo con `textContent`.
- Fuera de `app/`, para `security`: `product/doc/compliance-checklist.md` (tabla regla, dónde está en el código, cómo se comprueba), `README.md` y `.env.example` con `ENVIRONMENT`, `API_KEYS` (vacía) y `RATE_LIMIT_PER_MINUTE`.
- Fuera de `app/`, para `deploy`:
  - `Dockerfile`: `python:3.12-slim`, usuario sin root, `uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}`.
  - `.dockerignore` (`.env`, `tests/`, `e2e/`, cachés) y `.gitignore` (`.env`, `.venv/`, cachés, `.coverage`).
  - `.github/workflows/ci.yml`: `style` -> `unit` -> `e2e` -> `docker`, encadenados con `needs`, en push y pull request.
  - `render.yaml`: servicio con el nombre del repositorio, `runtime: docker`, `plan: free`, `healthCheckPath: /health`, `autoDeployTrigger: checksPass`, variables fijas y secretos `API_KEYS`, `CF_ACCOUNT_ID`, `CF_API_TOKEN` con `sync: false`; sin `LANGSMITH_API_KEY`.
  - `scripts/smoke.py <url>`: la clave sale de `SMOKE_API_KEY`.
- `product/requirements.txt`: lo revisa `deploy` y lo cambia el developer si falta algo (por ejemplo `pylint` para el trabajo `style`).
- `product/e2e/` (lo actualiza `qa-e2e`): escribe la clave de `E2E_API_KEY` en `api-key` antes de cada prueba.

## Flujo de una pregunta

1. La persona escribe la clave en `data-testid="api-key"` (se guarda en `sessionStorage`), escribe la pregunta y pulsa `send`; el JS llama a `POST /ask` con `X-API-Key`.
2. El middleware fija el `request_id` y toma la hora de inicio (sin cambios).
3. `require_client` busca la clave con `compare_digest`. Sin clave o inválida: `401` y evento `request` sin cliente. Si es válida, el nombre del cliente pasa al contexto del log.
4. `RateLimiter` cuenta la petición del cliente en el minuto actual con el reloj inyectado. Si pasa de `RATE_LIMIT_PER_MINUTE`: `429` con `Retry-After`.
5. FastAPI valida el cuerpo; pregunta vacía o demasiado larga da `422`.
6. `router.choose_model`, agente, modelo, herramientas y `pricing` funcionan como en la sesión 3; `audit`, `agent_run` y la traza llevan `client`.
7. La ruta responde igual que en la sesión 3; el middleware emite `request` con `client` y devuelve `X-Request-ID`.
8. El JS pinta con `textContent`. Con `401` muestra «Clave inválida»; con `429`, «Demasiadas preguntas; espera N segundos».
9. Al arrancar (antes del paso 1): `load_settings` valida `API_KEYS`; con `ENVIRONMENT=production`, `compliance` se niega a arrancar si una regla falla.

## Pruebas

Gherkin (pytest-bdd), sin red, con reloj de prueba:
- Sin clave y con clave inválida: `POST /ask` y `GET /metrics` dan `401` con el cuerpo exacto.
- Con clave válida: `200`; `GET /`, `/health` y `/docs` responden sin clave.
- El nombre del cliente está en el log (`request`, `audit`, `agent_run`) y la clave no aparece en el log, en `/metrics` ni en ningún cuerpo de error.
- Límite: con `RATE_LIMIT_PER_MINUTE=2`, la tercera petición del mismo cliente da `429` con `Retry-After` correcto; otro cliente sigue pasando; al avanzar el reloj un minuto se libera.
- `ENVIRONMENT=production` no arranca con `fake`, con `API_KEYS` vacía, con una clave de 15 caracteres, y con trazas encendidas y `HIDE_INPUTS=false` o `HIDE_OUTPUTS=false`. Con una configuración correcta arranca.
- `API_KEYS` mal formada no arranca; el mensaje trae la entrada y su largo, no su valor.
- Los escenarios de las sesiones 1 a 3 siguen pasando, ahora con clave (las fixtures la ponen).

Unitarias:
- `security`: `parse_api_keys` (vacía, un cliente, varios, espacios, sin `:`, vacíos, repetido, clave con `:`), `authenticate` (acierto, fallo, ausente, claves de igual prefijo), `RateLimiter` (borde exacto en el límite y en el límite más uno, cambio de minuto, clientes independientes, `Retry-After` entre 1 y 60).
- `compliance`: cada regla por separado y todas juntas, 15 y 16 caracteres, `development` no aplica nada, mensajes sin clave.
- `config`: valores por omisión nuevos, `ENVIRONMENT` inválido, `RATE_LIMIT_PER_MINUTE` inválido, `repr` sin claves.
- `observability`: `client` en el evento con cliente y ausente sin él.
- `main`: encabezados `Retry-After`, `401` antes de validar el cuerpo (cuerpo inválido sin clave da `401`, no `422`).

Fuera de `qa-unit`: `qa-e2e` actualiza `product/e2e/` (clave de `E2E_API_KEY` y caso de clave equivocada con «Clave inválida»); `verification contract` y `verification production <url>` ya existen; los archivos de `deploy` se comprueban con `scripts/smoke.py` y las pruebas de `tests/test_production.py` y `tests/test_publish.py`. Cobertura mínima: 80 %.

## Riesgos

- Fuga de claves: `repr=False`, errores con entrada y largo, ningún evento con el encabezado, una prueba busca la clave en log, `/metrics` y errores; `.env` en `.gitignore` y `.dockerignore`, y secretos con `sync: false`.
- Ataque de tiempo en la comparación: `hmac.compare_digest` contra todas las claves, sin salir temprano.
- Límite en memoria por proceso: con varios procesos o reinicios no es exacto. Es aceptable para el plan `free` (un proceso); se documenta en ADR 0011 y se cambia por Redis si se escala.
- El límite crece sin tope con clientes desconocidos: solo se cuentan clientes autenticados, así que el número de entradas está acotado por `API_KEYS`.
- Producción arranca mal configurada: `compliance` la detiene y la lista de reglas va a `doc/compliance-checklist.md` con su prueba.
- Romper las sesiones 1 a 3 al exigir clave: los parámetros nuevos son opcionales; `verification/server.py` ya pone claves y un límite alto; con `API_KEYS` vacía en `development`, `/ask` y `/metrics` devuelven `401` (no hay acceso abierto). Conviene que la persona confirme esta decisión.
- Render publica algo roto: `autoDeployTrigger: checksPass` ata la publicación al pipeline; después, prueba de humo con `verification production <url>`.
- Nombre del servicio de Render choca con uno existente: se usa el nombre del repositorio que da la persona.
- Plan `free` duerme el servicio: la prueba de humo espera hasta un minuto; se documenta.
- `pylint` y Playwright en el CI sin estar en `requirements.txt`: `deploy` lo revisa y lo reporta; el developer lo agrega.
- Los tres agentes que corren en paralelo (`security`, `deploy`, `qa-e2e`) tocan carpetas distintas; el contrato de nombres (`E2E_API_KEY`, `SMOKE_API_KEY`, `X-API-Key`, `data-testid`) queda fijo en este plan.

## Sesion 5: enmascarado de PII (CURP y correo)

Parte de las sesiones 1 a 4, que siguen igual. Una sola regla: la CURP y el correo no vuelven a salir del servidor (respuesta, modelo, trazas ni log). Se enmascara; la petición se atiende. Decisión en ADR 0013.

### Modulos

- `pii.py` (nuevo): funciones puras, sin red ni estado. Una función `mask(text)` que devuelve el texto enmascarado y los conteos de CURP y correos (para la auditoría), y una variante que solo devuelve el texto (para el log). La CURP se reemplaza por `[CURP]` y el correo por `[EMAIL]`. La CURP solo se detecta como palabra completa de 18 caracteres con la estructura oficial: si hay una letra o un dígito pegado justo antes o después, no se enmascara. El correo admite un TLD de 2 a 24 letras. Los patrones se compilan una vez al importar y se aplican sin retroceso costoso. Idempotente: los marcadores no coinciden con ningún patrón.
- `config.py` (cambia): `Settings` agrega `pii_masking: bool = True`; `load_settings` lo lee con `_boolean(env, "PII_MASKING", True)` junto a `hide_inputs`; se documenta en la docstring de `Settings`.
- `compliance.py` (cambia): `check_production` agrega, tras la regla de trazas, `PII_MASKING must be 'true' in production`; solo aplica con `environment == "production"`, igual que las demás. `create_app` ya lanza `ValueError` con la lista.
- `observability.py` (cambia): `JsonLogger` recibe un parámetro opcional de enmascarado (por ejemplo `mask_pii`, `True` por omisión). En `_serialize`, los valores de cada campo (en profundidad: diccionarios, listas, tuplas, claves y el resultado de `default=str`) pasan por `mask_deep` antes de `json.dumps`; la línea ya serializada no se enmascara, porque con `ensure_ascii=True` un salto de línea o una letra con tilde pegados a un correo salen como `\n` o `ñ` y un patrón sobre la línea rompería el JSON. Con `PII_MASKING=false` no enmascara. Cubre todos los eventos y campos, incluidos `audit` con `args`. `create_app` lo construye con `settings.pii_masking`.
- `main.py` (cambia): en `ask`, tras validar el largo con `body.question` original y antes de `choose_model` y `agent.run`, se enmascaran `question` e `history` (`user` y `assistant`); tras `agent.run` se enmascara `result.answer` antes del `return`. Cada vez que hay conteos mayores que cero se emite `logger.log("audit", action="pii_masked", where=..., curp=n, email=m)`: un evento por cada `where` (`question`, `history` o `answer`) con los conteos sumados (el historial entero es un solo evento). Un manejador de `RequestValidationError` (instalado en `create_app`) enmascara solo las CURP y los correos que contenga el valor devuelto por el `422`; el resto del error no se altera, y si el cuerpo no trae el valor, no cambia nada. `PII_MASKING=false` (solo desarrollo) apaga las tres capas: entrada, salida y log (y el manejador del `422`).
- `agent.py`: sin cambios; recibe ya el texto enmascarado y su `audit` y `agent_run` pasan por el logger.
- `product/doc/compliance-checklist.md` (lo actualiza `security`): fila nueva para la regla de `PII_MASKING`, con su lugar en el código y su prueba. `README.md` y `.env.example`: variable `PII_MASKING`.

### Flujo de una pregunta con PII

1. La persona escribe una pregunta con una CURP o un correo; la página la muestra tal cual (no cambia) y llama a `POST /ask`.
2. Pasan `observe`, `require_client` y la validación del cuerpo; el largo se mide con el texto original (`422` si vacía o más de `max_question_chars`).
3. Entrada: `pii` enmascara `question` y cada `content` del historial. Si hubo coincidencias se emite `audit` `pii_masked` con `where=question` o `where=history` y los conteos, sin el valor.
4. `choose_model` y el agente trabajan con el texto enmascarado; el modelo, el gateway y las trazas nunca ven el dato. Las herramientas siguen igual.
5. Salida: `result.answer` se enmascara antes de devolverse; si cambió, `audit` `pii_masked` con `where=answer`. La forma de la respuesta no cambia.
6. Log: `JsonLogger._serialize` enmascara los valores de cada campo antes de serializar (`request`, `audit`, `agent_run`, `error`, `invalid_*`); es la red de seguridad de todo lo anterior.
7. Auditoría: los eventos `pii_masked` llevan `client` y `request_id` como cualquier evento, y solo conteos.
8. Un `422` de validación que devuelva el valor recibido lo devuelve con las CURP y los correos enmascarados; el resto del error queda igual.

### Pruebas

Gherkin (pytest-bdd), sin red:
- Pregunta con CURP y correo: el modelo simulado no los recibe, la respuesta no los trae, el log capturado no los trae y aparecen `[CURP]` y `[EMAIL]`.
- Historial con PII en mensajes `user` y `assistant`: el modelo no la recibe.
- El modelo inventa un correo o una CURP en `answer`: la respuesta sale enmascarada.
- Auditoría: `audit` `pii_masked` con `where` y conteos correctos y sin el valor, incluso en el argumento de una herramienta.
- CURP pegada a una letra o a un dígito (antes o después) no se enmascara; separada por espacio o puntuación, sí.
- Una petición con CURP en la pregunta y en el historial emite un `audit` por cada `where`, con los conteos sumados.
- `422` con valor devuelto sale con las CURP y los correos enmascarados y el resto del error intacto; el largo se valida con el original.
- Una línea de log con caracteres no ASCII y un correo o una CURP sigue siendo JSON válido y sale enmascarada.
- Con `PII_MASKING=false` en desarrollo no se enmascara en ninguna de las tres capas.
- `ENVIRONMENT=production` con `PII_MASKING=false` no arranca; con `true` o sin la variable arranca. `PII_MASKING` mal escrito no arranca.

Unitarias (`qa-unit`, antes del código):
- `pii`, CURP: válida en mayúsculas y minúsculas, dentro de una frase, varias en un texto; no con mes `13`, estado inexistente o 17 caracteres; no con espacios o guiones; no con una letra o un dígito pegado justo antes o después (19 caracteres seguidos).
- `pii`, correo: simple, con `+`, con subdominios, varios, TLD de 2 y de 24 letras (con 25 no); no `@juan` ni texto sin dominio.
- `pii`, falsos positivos (`EMP-0004`, «Jorge Díaz», departamentos, fechas), idempotencia y una entrada de 2000 caracteres sin lentitud (con tope de tiempo).
- `observability`: `JsonLogger` enmascara campos anidados y listas; con el enmascarado apagado deja la línea igual.
- `config` y `compliance`: valor por omisión `true`, valores inválidos, regla por separado y junto a las demás; `development` no aplica.
- `main`: conteos de `pii_masked` por `where`; sin coincidencias no hay evento.
- `qa-e2e`: en la página, una pregunta con CURP y correo no los muestra en la respuesta.

Verificaciones de la fábrica (las escribe el supervisor, no los agentes):
- `verification/server.py` captura su propia salida (el log del servidor de prueba) para poder buscar en ella.
- Prueba de contrato nueva en `verification contract`: envía una CURP y un correo de prueba y comprueba que no están en la respuesta ni en el log capturado.
- Quinta comprobación de `verification production <url>`: CURP inventada y correo `@example.com`; la respuesta no los trae.
- Tras publicar y con aprobación humana: descargar los logs de Render y buscar los valores de prueba (cero coincidencias, con `[CURP]` o `[EMAIL]` presentes).

### Riesgos

- Falsos positivos: la CURP exige estructura completa (vocal o `X`, mes 01 a 12, estado válido, consonantes) y el correo exige dominio con TLD; se prueban `EMP-0004`, nombres, departamentos y fechas. Se acepta enmascarar de más una CURP inexistente (no se valida el dígito verificador).
- CURP dentro de una cadena más larga (letra o dígito pegado) no se enmascara por diseño; es un límite aceptado.
- Ofuscación: variantes con espacios, guiones, «arroba», otro alfabeto o dato repartido entre mensajes no se detectan; es un límite aceptado y se documenta en el ADR y el README.
- Rendimiento con 2000 caracteres (y con líneas de log largas): patrones compilados una vez, sin cuantificadores anidados ni retroceso catastrófico; prueba con tope de tiempo, también con entradas hostiles (muchos `@` o puntos seguidos).
- Que el marcador no vuelva a coincidir: `[CURP]` y `[EMAIL]` no cumplen ningún patrón; prueba de idempotencia, importante porque el log enmascara texto ya enmascarado.
- Enmascarar la línea serializada podría tocar la estructura JSON o un escape (`\n`, `ñ`): por eso se enmascaran los valores antes de `json.dumps`; prueba de que cada línea sigue siendo JSON válido, también con saltos de línea y tildes pegados a un correo.
- Pruebas existentes que usen correos o textos parecidos a CURP: se revisan las fixtures y los escenarios de las sesiones 1 a 4 antes de que el developer corra; las que cambien se reportan, no se ajustan en silencio.
- Dato que sale por otro camino (`422`, trazas): el `422` se cubre con el manejador; las trazas reciben solo texto ya enmascarado.
- Apagar la protección en producción: `compliance` lo impide al arrancar; en `development` se puede apagar solo para depurar.

## Sesion 6: cost_usd en agent_run y documentacion OpenAPI publica

Parte de las sesiones 1 a 5, que siguen igual. Dos cambios pequeños: el evento `agent_run` trae `cost_usd` (el mismo número que devuelve `/ask`) y la API tiene documentación OpenAPI completa y pública. La forma de `/ask`, `/metrics` y el evento `request` no cambia. Decisión en ADR 0014.

### A. Donde se calcula el costo

Hoy `Agent.run` emite `agent_run` sin conocer precios y `main.py` calcula el costo después con `_request_cost`. Opciones:

- Emitir `agent_run` desde `main`: un solo cálculo, pero `agent_run` deja de ser del agente, hay que mover sus campos (`stopped`, `question_chars`) y se rompen `test_agent_events.py`, `observability.feature` y `production.feature`, que construyen el agente solo. Descartada.
- Evento aparte (por ejemplo `request_cost`): no cumple la spec, que pide el campo en `agent_run`; además repite `request_id` y complica la suma en Render. Descartada.
- Pasar al agente una función de costo: el agente sigue emitiendo `agent_run` y lo completa. Recomendada.

Decisión: `Agent` recibe un parámetro opcional `cost_fn` (función que toma la lista de llamadas y devuelve USD). `main.py` lo arma con la tabla de precios y el modelo elegido, reutilizando `_request_cost` (la única fórmula; no se escribe otra). En `Agent.run`, tras el bucle y antes de emitir, se calcula `cost_usd` una sola vez, se guarda en `AgentResult` (campo nuevo `cost_usd`, `None` por omisión) y se agrega a `agent_run`. `main.py` deja de llamar a `_request_cost` por su cuenta: usa `result.cost_usd` para la respuesta y para `metrics.add_cost`. Así `/ask`, `/metrics` y el log salen del mismo número.

Cuidados:
- Sin `cost_fn` (todas las pruebas y escenarios actuales que arman el agente solos) el campo `cost_usd` no se emite y el evento queda igual; nada existente se rompe.
- Modelo sin precio: `PriceTable.cost` lanza `ValueError` y se propaga igual que hoy (500 por el middleware, no 0). Diferencia a documentar: el error ahora ocurre antes de emitir `agent_run`, así que ese evento no sale en ese caso (sí salen `error` y `request`). Se prueba.
- Llamada cacheada: la tabla ya da 0.0; el campo es `float`, nunca texto, y no lleva datos de la persona.
- `502` (`ModelUnavailable`): ocurre dentro del bucle, antes del costo; sin cambios.
- `AgentResult.cost_usd` no se serializa en ninguna parte de la respuesta; el diccionario que devuelve `/ask` se arma campo por campo y queda igual.

### B. Documentacion OpenAPI sin cambiar el comportamiento

Todo en `main.py` (y la página sigue igual):
- Metadatos: `FastAPI(title, summary, description, version, openapi_tags)` en español, con una etiqueta por grupo (por ejemplo `Sistema`, `Consulta`, `Observabilidad`). No se toca `docs_url`, `redoc_url` ni `openapi_url`: `/docs`, `/redoc` y `/openapi.json` quedan por omisión y públicos, porque el middleware y `require_client` no los cubren. No hay variable para apagarlos.
- Cada ruta (`/`, `/health`, `/ask`, `/metrics`) con `summary`, `description` y `tags` en el decorador. `/` se documenta como página HTML (`response_class` y `include_in_schema=True`, sin cambiar lo que devuelve).
- Modelos de documentación: `AskRequest` e `HistoryMessage` ya existen; se les agregan `Field(description=..., examples=...)` con `EMP-0004` (ejemplos sin clave, CURP ni correo) y `model_config` con `json_schema_extra`. Modelo nuevo `AskResponse` con los diez campos reales, mismos nombres y tipos: `model`, `route`, `cached_calls`, `cost_usd`, `answer`, `steps`, `tools_used`, `input_tokens`, `output_tokens`, `request_id`. Modelos para `/health` y `/metrics` (`pid`, `requests`, `error_rate`, `latency_ms`, `tokens`, `cost_usd`, `slo`) y para los errores: `{"detail": str}` (401, 429), `{"detail": str, "request_id": str}` (502) y la forma de lista de FastAPI para 422.
- Respuestas de error con `responses={...}` en `/ask` (401, 422, 429, 502) y `/metrics` (401, 422 no aplica; 429): cada código con descripción y ejemplo. El `429` declara el encabezado `Retry-After`. El `422` documenta las dos formas reales: la lista de FastAPI y `{"detail": "Invalid question length"}`.
- Seguridad: `APIKeyHeader(name="X-API-Key", auto_error=False)` declarado como esquema `ApiKeyAuth` y usado como dependencia en `/ask` y `/metrics` solo para que aparezca en el esquema y en el botón de autorizar. Con `auto_error=False` no lanza nada por sí mismo: la autenticación sigue en `require_client` (que lee el encabezado de `request.headers`), así que sin clave el `401` sigue siendo `{"detail": "invalid or missing API key"}` y no el `403` por omisión de FastAPI. La dependencia de seguridad no devuelve ni guarda la clave.
- Riesgo de `response_model`: si se declara en `/ask`, FastAPI valida y filtra el diccionario devuelto: un campo ausente en el modelo desaparecería, un tipo distinto (por ejemplo `cost_usd` como entero) se convertiría o daría 500, y el `JSONResponse` del `502` quedaría fuera de la validación. Como la forma real no debe cambiar, el plan evita `response_model` y declara el modelo solo en `responses={200: {"model": AskResponse}}` (documentación, sin validar ni filtrar). Si el developer prefiere `response_model`, debe poner `response_model_exclude_unset` desactivado y una prueba que compare los campos de la respuesta con los de hoy. Se recomienda lo primero.
- Una prueba de contrato de campos (ver pruebas) fija que el esquema `AskResponse` y la respuesta real tengan exactamente las mismas claves; así el esquema no se aleja de la realidad.
- README y checklist: `README.md` agrega la sección «Documentación de la API» (dónde está, que es pública, cómo usar el botón de autorizar con una clave de prueba, tabla de rutas, códigos y si piden clave; la clave del ejemplo es un marcador, no una real). `doc/compliance-checklist.md` agrega una fila: la documentación es pública a propósito porque no contiene secretos, y la prueba que lo comprueba.

### Archivos de product/ por agente

- `qa-unit` (solo `product/tests/`): `tests/test_cost_in_agent_run.py` (nuevo), `tests/test_openapi_docs.py` (nuevo) y un `.feature` con sus pasos si se prefiere Gherkin (por ejemplo `tests/features/api_docs.feature` y su archivo de pasos). Toca `tests/conftest.py` solo si hace falta una fixture de log capturado. No edita las pruebas existentes.
- `developer`: `app/agent.py` (parámetro `cost_fn`, campo `AgentResult.cost_usd`, campo en `agent_run`), `app/main.py` (armar `cost_fn`, quitar el cálculo aparte, metadatos, modelos de documentación, `responses`, esquema de seguridad), y `requirements.txt` solo si hiciera falta (no se espera). No toca `observability.py` (el logger ya serializa números) ni `pricing.py` ni `static/`.
- `observability`: revisa que `cost_usd` salga como número en el log y que `observability.py` y `doc/` hablen del campo nuevo; solo cambia `app/observability.py` si hace falta (no se espera) y la parte de log de `product/README.md`.
- `security`: `product/doc/compliance-checklist.md` (fila de documentación pública) y, con `README.md`, la tabla de rutas y códigos; revisa que el esquema no contenga claves, CURP ni correos.
- `architect` (este plan): `product/doc/adr/0014-public-docs-and-request-cost.md` y `product/doc/architecture.md`.
- `deploy`: sin cambios en `Dockerfile`, CI ni `render.yaml`; `scripts/smoke.py` no cambia. La sexta comprobación (`GET /openapi.json`) la agrega el supervisor en `verification/`, no los agentes.
- `qa-e2e`: ninguna prueba nueva (la spec lo pide así); se verifica que las pruebas existentes de la página sigan pasando.

### Pruebas (qa-unit, rojas primero)

Unitarias y BDD, sin red:
- `agent_run` trae `cost_usd` y es igual al `cost_usd` de la respuesta de `/ask`, con el log capturado y el modelo simulado.
- `cost_usd` en `agent_run` es `int` o `float`, no `str`, y vale 0 con una llamada cacheada; con dos llamadas (una cacheada y otra no) suma solo la no cacheada.
- Un modelo sin precio sigue dando error (no 0) y no emite `agent_run` con `cost_usd` en cero.
- Sin `cost_fn`, `Agent` emite `agent_run` sin el campo `cost_usd` (compatibilidad con las pruebas existentes); con `cost_fn` se llama una sola vez por corrida (función espía).
- La respuesta de `/ask` tiene exactamente los diez campos de hoy (conjunto de claves) y `/metrics` conserva sus claves; el `cost_usd` de `/metrics` es la suma de los de `/ask`.
- `/docs` y `/openapi.json` dan `200` sin clave; `/redoc` sigue respondiendo.
- El esquema tiene las rutas `/`, `/health`, `/ask`, `/metrics`, cada una con `summary`, `description` y `tags`; `/ask` y `/metrics` declaran `401` y `429`, y `/ask` además `422` y `502`; el `429` declara `Retry-After`.
- El esquema declara `X-API-Key` como esquema de seguridad `apiKey` en el encabezado y `/ask` y `/metrics` lo exigen; `/`, `/health` no.
- Las propiedades del esquema de respuesta de `/ask` coinciden con las claves de una respuesta real.
- Sin clave, `/ask` y `/metrics` dan `401` con el cuerpo `{"detail": "invalid or missing API key"}` (no `403`), también con el esquema de seguridad instalado; cuerpo inválido sin clave sigue dando `401`, no `422`.
- El `502` conserva su cuerpo (`detail` y `request_id`) con el modelo no disponible.
- El esquema serializado no contiene ninguna clave de `API_KEYS` de las fixtures, ni una CURP ni un correo (se busca con `pii.mask_text`: no cambia nada) y los ejemplos usan `EMP-0004`.

Las pruebas de contrato de `verification/` (cost_usd del log igual al de `/ask`; `/docs` y `/openapi.json` sin clave) y la sexta comprobación de `verification production <url>` las escribe el supervisor.

### Riesgos

- `response_model` filtra o altera la respuesta real: se evita (solo `responses={200: {"model": ...}}`) y una prueba compara claves reales con el esquema.
- El esquema de seguridad cambia el `401` por un `403` de FastAPI: `auto_error=False` y prueba del cuerpo exacto del `401`.
- Calcular el costo dos veces o con otra fórmula: `main` solo pasa `_request_cost` como `cost_fn`; la prueba con función espía fija una sola llamada.
- Romper pruebas existentes de `agent_run`: `cost_fn` es opcional y sin él el evento no cambia; `qa-unit` no edita las pruebas viejas, y si alguna falla se reporta.
- Modelo sin precio devuelve 0 por error: no se captura `ValueError`; prueba explícita. Cambio conocido: `agent_run` no sale en ese caso.
- Ejemplos o descripciones con datos sensibles: solo `EMP-0004` y marcadores; prueba sobre el esquema serializado y revisión de `security`.
- Documentación pública revela rutas internas: solo las cuatro rutas del producto; no hay secretos ni valores de configuración en el esquema. Es una decisión de la spec (ADR 0014).
- `/docs` carga su interfaz desde un CDN: sin red la página puede no verse, pero `/openapi.json` sigue sirviendo; por eso no hay prueba e2e y el esquema se comprueba por contrato.
- Esquema que se aleja de la realidad con el tiempo: la prueba de claves de `AskResponse` contra la respuesta real lo atrapa.
- `cost_usd` en el log permite sumar el gasto desde Render; no lleva datos de la persona, solo el número, y el log ya enmascara PII.
