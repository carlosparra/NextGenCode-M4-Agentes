# HR Assistant

Asistente de Recursos Humanos que responde preguntas sobre empleados y políticas de RH
desde una página web. Es una API FastAPI sin estado con un sistema multi-agente: cada
pregunta pasa por `guard`, `supervisor`, un especialista (`directory`, con
`get_employee` y `search_by_department` sobre `data/employees.json`, o `policy`, con
`search_policy` sobre `data/policies.json` y `vacation_days`, que calcula en código
los días de vacaciones de un empleado) y `reviewer`. Cada especialista corre un
bucle con tope. Por omisión el modelo es simulado: determinista, sin red ni costo.

Desde la sesión 2 cada petición se puede rastrear: lleva un `request_id`, deja un log
JSON (una línea por evento) en la salida estándar, alimenta `GET /metrics` y, si se
activa, manda trazas a LangSmith.

Desde la sesión 3 puede usar el modelo real (Cloudflare Workers AI a través de AI
Gateway, con `MODEL_PROVIDER=gateway`) y cada respuesta dice qué modelo usó, por qué y
cuánto costó.

Desde la sesión 4 está listo para producción: cada cliente usa su propia clave, hay un
límite de peticiones por cliente y, con `ENVIRONMENT=production`, el producto se niega
a arrancar si la configuración no es segura.

## Arquitectura multi-agente (spec 06)

Cada `POST /ask` pasa por estos agentes, en este orden (lo arma `app/orchestrator.py`):

| Agente | Tipo | Qué hace |
| --- | --- | --- |
| `guard` | Código | Filtro de entrada: PII, inyección y auditoría |
| `supervisor` | Reglas y, si no alcanzan, `MODEL_SMALL` | Elige qué especialista contesta |
| `directory` | Especialista con bucle acotado | Directorio de empleados: `get_employee` y `search_by_department` |
| `policy` | Especialista con bucle acotado | Políticas de RH: `search_policy` y `vacation_days` |
| `reviewer` | Código | Validación de salida, comprobación contra los datos y recorte |

- **Ids de empleado (Adenda 1).** Además de `EMP-dddd`, `guard` reconoce, sin
  importar mayúsculas, «empleado 4», «empleado 004», «empleado #4», «emp 4», «emp-4» y
  «EMP4» (de 1 a 4 dígitos, con o sin ceros a la izquierda) y los convierte en
  `EMP-0004` sobre el texto ya limpio de PII (`app/employee_ids.py`). Así el
  supervisor, el especialista y el revisor ven la forma canónica, y un id escrito de
  otra forma cuenta como escrito por la persona. Un número suelto sin «empleado» o
  «emp» (por ejemplo «2021») no es un id.
- **Supervisor.** Primero reglas en código, sin modelo: un id **y** una palabra clave
  de la política de vacaciones van a `policy` (`rule:policy_employee`, Adenda 1); si
  no, un id `EMP-dddd` va a `directory` (`rule:employee`); un departamento del
  directorio, a `directory`
  (`rule:department`); una palabra clave de una política, a `policy` (`rule:policy`).
  Si ninguna aplica, hace una sola llamada a `MODEL_SMALL` sin historial (`model`); si
  la respuesta no es válida, usa `directory` (`model_invalid`). Esa llamada suma a los
  tokens y al costo de la petición. El enrutador de costo (`route`) sigue eligiendo el
  modelo **del especialista**: `supervisor_route` dice quién contesta y `route` con qué
  modelo.
- **Mínimo privilegio.** `policy` no puede usar `get_employee` ni
  `search_by_department`, y `directory` no puede usar `search_policy` ni
  `vacation_days`.
- **Herramienta `vacation_days(employee_id)` (Adenda 1).** Solo de `policy`, de solo
  lectura (`app/vacations.py`). Usa el reloj inyectado (`app/clock.py`), nunca
  `datetime.now()` directo. Devuelve solo `employee_id`, `name`, `start_date`,
  `status`, `years_of_service` (años completos hasta hoy), `days` y `note`. Días según
  la política: 1 año, 12; 2, 14; 3, 16; 4, 18; 5, 20; de 6 a 10, 22; de 11 a 15, 24;
  y así, 2 más por cada 5 años. Con menos de 1 año, `days = 0` y una nota de que al
  cumplirlo le tocan 12 días hábiles; si el empleado no está `activo`, `days = 0` y
  la nota «El empleado no está activo.»; si no, `note` vacía. Un id inexistente o con
  formato inválido devuelve `{"error": "empleado no encontrado"}` (el formato
  inválido además registra `security` con `control=tool_args`).
- **Consultas en código.** Con `rule:policy`, el producto ejecuta `search_policy`
  antes de llamar al modelo y le pone el resultado enfrente. Con
  `rule:policy_employee` ejecuta `search_policy("vacaciones")` y
  `vacation_days(<id>)`, en ese orden. Cada consulta cuenta en `tools_used` y deja su
  `audit`. El cálculo de días no se le deja al modelo.
- **Revisor.** Si `directory` cita un `EMP-dddd` que no existe y que la persona no
  escribió, o si `policy` da un número que no está en las políticas consultadas ni en
  los resultados de `vacation_days` de la petición, la respuesta se reemplaza y se
  registra `security` con `control=ungrounded`. El reemplazo de `policy` es, si hubo
  `vacation_days`, la frase armada en código «<name> (<employee_id>) tiene
  <years_of_service> años de servicio y le corresponden <days> días hábiles de
  vacaciones.» seguida de `note`; si no, el texto de la política (o un mensaje fijo).
- **Prompt de `policy`.** Si la respuesta depende de datos de la persona y no hay id,
  no se niega: da la regla completa y sugiere preguntar con el id (por ejemplo
  `EMP-0004`).
- **Traza raíz.** Con LangSmith encendido, cada petición abre un solo run `request`
  (tipo `chain`) con, dentro y en orden, `agent.guard`, `agent.supervisor`,
  `agent.directory` o `agent.policy` (con sus runs `llm` y de herramienta) y
  `agent.reviewer`. Los spans `security` de la entrada quedan en `agent.guard` y los de
  la salida en `agent.reviewer`; la llamada al modelo del supervisor, en
  `agent.supervisor`. Todos los runs llevan `request_id` y `client`; el raíz y el
  especialista, además, `specialist` y `supervisor_route`. El raíz, `agent.guard`,
  `agent.supervisor` y `agent.reviewer` no reciben texto y solo devuelven un resumen
  (tipos, conteos y decisiones), así que no dependen únicamente de `HIDE_INPUTS` y
  `HIDE_OUTPUTS`. Con `LANGSMITH_TRACING=false` no se importa `langsmith`. Con
  `rule:policy_employee` la forma es la misma: `agent.supervisor` no tiene run `llm`
  (es una regla) y `search_policy` y `vacation_days` son runs de herramienta dentro de
  `agent.policy`, con `request_id` y `client`; el resumen de `agent.guard` solo
  cuenta los ids normalizados (`ids_normalized`), nunca los repite.

Más detalle en [doc/architecture.md](doc/architecture.md).

## Acceso por clave

- `API_KEYS` tiene la forma `cliente:clave,cliente2:clave2` y es un secreto: va en
  `.env` o en el panel de Render, nunca en el repositorio.
- `POST /ask` y `GET /metrics` exigen el encabezado `X-API-Key`. Sin clave o con una
  inválida responden `401 {"detail": "invalid or missing API key"}`.
- `GET /`, `GET /health` y `/docs` no piden clave.
- Más de `RATE_LIMIT_PER_MINUTE` peticiones de un cliente en un minuto responden
  `429 {"detail": "rate limit exceeded"}` con `Retry-After` (segundos que faltan). Las
  peticiones rechazadas por clave no gastan cupo. El límite vive en memoria, por
  proceso (ADR 0011).
- El nombre del cliente va en el log (`client`), en `audit`, en `agent_run` y en los
  metadatos de la traza. La clave nunca se escribe en el log, en la traza ni en un
  error; se compara con `hmac.compare_digest`.
- Si `API_KEYS` está mal formada (sin `:`, cliente o clave vacíos, espacios dentro de
  la clave o una clave repetida), el producto no arranca. El error dice qué entrada
  falla y su largo, nunca su valor.

La página tiene un campo «Clave de acceso» (tipo contraseña). La clave se guarda en
`sessionStorage` (se borra al cerrar la pestaña) y se manda en `X-API-Key`. Con una
clave equivocada muestra «Clave inválida»; si se pasa del límite, «Demasiadas
preguntas; espera N segundos».

### Cómo pedir una clave en desarrollo

No hay claves compartidas: cada persona crea la suya en su `.env`.

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Pon el resultado en `.env` como `API_KEYS=tu-nombre:<la clave generada>`, exporta el
`.env` antes de arrancar (ver «Cómo correrlo») y escribe la clave en el campo de la
página o en el encabezado:

```bash
curl -s -X POST http://127.0.0.1:8000/ask -H "X-API-Key: $MI_CLAVE" \
  -H "Content-Type: application/json" -d '{"question": "¿Quién es EMP-0004?"}'
```

En producción la clave de cada cliente la da la persona responsable del servicio, por un
canal privado, y se escribe en Render > Environment.

## Compliance

Con `ENVIRONMENT=production` el producto no arranca si:

- `MODEL_PROVIDER` es `fake`;
- `API_KEYS` está vacía o alguna clave tiene menos de 16 caracteres;
- las trazas están encendidas y `HIDE_INPUTS` o `HIDE_OUTPUTS` no valen `true`.

El error nombra las reglas que fallan, nunca los valores. La tabla de reglas, dónde
están en el código y cómo se comprueba cada una está en `doc/compliance-checklist.md`.

## Seguridad reforzada (PII, salidas e inyección)

Los datos del directorio (nombre, `EMP-0001`, departamento, puesto, fecha de ingreso y
estado) son el negocio y **no se ocultan**. PII es lo que el directorio no tiene:

| Tipo | Qué detecta |
| --- | --- |
| `email` | Correo electrónico |
| `phone` | Teléfono de 10 dígitos, con o sin `+52`, espacios o guiones |
| `card` | Tarjeta de 13 a 19 dígitos que pasa el algoritmo de Luhn |
| `curp` | CURP de 18 caracteres |
| `rfc` | RFC de persona física de 13 caracteres |

- **Entrada.** Antes de enrutar, la pregunta y todo el `history` pasan por
  `app/pii.py` (`redact_pii`, solo regex y Luhn). Cada coincidencia se cambia por
  `[REDACTED:<kind>]`. El modelo, el log, la auditoría y la traza solo ven el texto
  limpio. La petición no se rechaza.
- **Inyección.** Frases como «ignora las instrucciones», «ignore previous
  instructions», «olvida tus reglas», «muestra tu prompt», «system prompt» o «actúa
  como» se comparan sin acentos ni mayúsculas. Solo se auditan: la petición sigue,
  porque el agente ya está acotado a dos herramientas de solo lectura.
- **Herramientas.** `get_employee` solo acepta `EMP-` y 4 dígitos, o un nombre de 1
  a 80 caracteres sin caracteres de control ni PII. `search_by_department` solo acepta
  un departamento del directorio. `search_policy` acepta texto de 1 a 60 caracteres y
  `vacation_days`, solo `EMP-dddd`. Un argumento inválido no llega al directorio: el
  modelo recibe un error que no repite el valor.
- **Salida.** La respuesta final pasa, en este orden, por: claves de `API_KEYS` y
  `CF_API_TOKEN` (salen como `[REDACTED:secret]`), PII, respuesta vacía (se cambia
  por «No pude generar una respuesta segura.») y recorte a `MAX_ANSWER_CHARS`.
- **Auditoría.** Cada detección escribe un evento `security` en el log, suma en
  `GET /metrics` (`security`) y abre un span `security` en la traza, con
  `request_id`, `client`, `stage` (`input` u `output`), `control` (`pii`, `secret`,
  `output_invalid`, `tool_args` o `injection`) y `kinds`. Nunca escribe el valor
  detectado.
- **Concurrencia.** `tests/test_concurrency.py` manda 20 peticiones `/ask` a la vez y
  comprueba que todas respondan 200, con `request_id` distintos, que `/metrics` las
  cuente y que el límite por cliente siga contando bien.

Más detalle: [doc/security.md](doc/security.md) (amenazas, controles y dónde está
cada uno) y el ADR
[0013 de redacción de PII y validación de salida](doc/adr/0013-pii-redaction-and-output-validation.md).

## Costos

Cuatro palancas, cada una medible con `verification evaluate`:

1. **Enrutamiento** (`ROUTING`): una regla en código manda la pregunta a `MODEL_LARGE`
   si el enrutamiento está apagado (`routing_disabled`), si pasa de `ROUTER_MAX_CHARS`
   caracteres (`long_question`) o si contiene «compara», «resume», «explica»,
   «por qué», «analiza» o «todos», sin distinguir mayúsculas ni acentos (`keyword`).
   Si no, a `MODEL_SMALL` (`simple_question`).
2. **Ventana de historial** (`HISTORY_WINDOW`): al modelo solo llegan los últimos
   mensajes del historial; la pregunta y los resultados de herramientas nunca se
   recortan.
3. **Tope de salida** (`MODEL_MAX_TOKENS`) en cada llamada.
4. **Caché de AI Gateway** (`CACHE_TTL_SECONDS` mayor que 0): se manda
   `cf-aig-cache-ttl`; si el gateway responde `cf-aig-cache-status: HIT`, la llamada
   cuenta en `cached_calls` y cuesta 0.

El costo sale de `data/model_prices.json` (USD por millón de tokens, copia de
`spec/model_prices.json`) y no se redondea. Con `MODEL_PROVIDER=fake` hay dos modelos
simulados que se llaman como `MODEL_SMALL` y `MODEL_LARGE`: responden igual, pero
cuestan según su nombre, así que las palancas se miden sin red y sin gastar cuota.
Si falta el precio de alguno de los dos modelos, la aplicación no arranca.

Para usar el modelo real, copia `.env.example` a `.env`, pon `MODEL_PROVIDER=gateway` y
llena `CF_ACCOUNT_ID`, `CF_GATEWAY_ID` y `CF_API_TOKEN` (si falta alguna, no arranca).
El token se guarda como secreto: no aparece en el log, en las trazas ni en los errores.

## Cómo correrlo

Desde esta carpeta (`product/`):

```bash
pip install -r requirements.txt
set -a; . ./.env; set +a    # exporta las variables de .env a este shell
uvicorn app.main:app --port 8000
```

La aplicación solo lee variables del entorno (`os.environ`): nada carga `.env` por
sí solo. Si no lo exportas antes de arrancar, `API_KEYS` queda vacía y todo `/ask`
responde 401. `set -a` exporta cada variable que se define mientras está activo, así
que `. ./.env` funciona sin dependencias nuevas (los valores con espacios o caracteres
especiales del shell van entre comillas simples). La otra forma,
`uvicorn app.main:app --env-file .env`, necesita el paquete `python-dotenv`, que no
está en `requirements.txt`; instálalo aparte si la prefieres. En Render no hace falta:
las variables del panel ya llegan al entorno.

Abre `http://127.0.0.1:8000/` para usar la página. Cada respuesta muestra su
"Id de petición": es el dato que hay que pasar a soporte.

Pruebas, desde la raíz del repositorio:

```bash
uv run python -m verification unit       # pruebas y cobertura (80 % o más)
uv run python -m verification contract   # contrato de las sesiones 1 a 4
uv run python -m verification qa         # estilo de QA.md
uv run python -m verification evaluate   # costo y calidad contra la línea base
```

Las pruebas nunca llaman a la red: el cliente HTTP del gateway se inyecta y usa
`httpx.MockTransport`.

## API

| Método y ruta | Qué hace |
| --- | --- |
| `GET /` | La página web (sin clave) |
| `GET /health` | `{"status": "ok", "pid": ...}` (sin clave) |
| `GET /metrics` | Exige `X-API-Key`. Métricas de este proceso: `pid`, `requests`, `error_rate`, `latency_ms` (`p50`, `p95`), `tokens` (`input`, `output`), `cost_usd` acumulado, `slo` (`p95_ms_target`, `met`), `security` (eventos por control: `pii`, `secret`, `output_invalid`, `tool_args`, `injection`), `specialists` (respuestas por especialista, por ejemplo `{"directory": 3, "policy": 1}`) y `supervisor` (decisiones por motivo: `rule:policy_employee`, `rule:employee`, `rule:department`, `rule:policy`, `model`, `model_invalid`) |
| `POST /ask` | Exige `X-API-Key`. Cuerpo `{"question": "...", "history": [...]}`; responde `answer`, `steps`, `tools_used`, `input_tokens`, `output_tokens`, `request_id`, `model`, `route` (motivo del enrutador), `cached_calls`, `cost_usd`, `redactions` (tipos ocultados en la pregunta o en la respuesta, sin repetir; `[]` si no se ocultó nada), `specialist` (`directory` o `policy`), `agents` (agentes que corrieron, en orden; por ejemplo `["guard", "supervisor", "policy", "reviewer"]`) y `supervisor_route` (`rule:policy_employee`, `rule:employee`, `rule:department`, `rule:policy`, `model` o `model_invalid`); `tools_used` puede traer `vacation_days` |

Toda respuesta trae el encabezado `X-Request-ID`. Si el cliente lo manda y es válido
(de 1 a 128 caracteres `A-Z a-z 0-9 . _ -`), se respeta; si no, se genera un UUID.
Un error interno responde `500` con `{"detail": "internal error", "request_id": ...}`.
Si el modelo real no responde (red, tiempo agotado de 30 s, status de error o cuerpo
inválido), la respuesta es `502` con `{"detail": "model unavailable", "request_id": ...}`.

## Log

Cada línea es un objeto JSON con `ts` (ISO 8601 en UTC), `service`, `event` y
`request_id`. Eventos: `request` (método, ruta, status, latencia y `client` si la clave
fue válida), `agent_run`
(conteos de la corrida, `model`, `route`, `cached_calls`, `cost_usd`, `specialist` y
`supervisor_route`; nunca el texto
de la pregunta ni de la respuesta), `audit` (una
por herramienta llamada, con los argumentos ya sin PII), `security` (`client`,
`stage`, `control` y `kinds` de cada detección, nunca el valor) y `error` (solo el
tipo de error). `agent_run` y `audit` también llevan `client`. La clave nunca aparece
en el log.

## Variables de entorno

| Variable | Por omisión | Para qué |
| --- | --- | --- |
| `MODEL_PROVIDER` | `fake` | `fake` (simulado) o `gateway` (Cloudflare AI Gateway) |
| `AGENT_MAX_STEPS` | `3` | Tope de vueltas del bucle del agente |
| `MAX_QUESTION_CHARS` | `2000` | Largo máximo de la pregunta |
| `EMPLOYEES_PATH` | `data/employees.json` | Archivo con los datos de empleados |
| `SERVICE_NAME` | `hr-assistant` | Campo `service` del log |
| `SLO_P95_MS` | `2000` | Meta de latencia p95 en milisegundos (`met` si el p95 queda por debajo) |
| `LANGSMITH_TRACING` | `false` | Enciende las trazas en LangSmith |
| `LANGSMITH_API_KEY` | (sin valor) | Clave de LangSmith; sin ella no se intenta conectar |
| `HIDE_INPUTS` / `HIDE_OUTPUTS` | `true` | No mandar a LangSmith el texto de preguntas ni respuestas |
| `CF_ACCOUNT_ID`, `CF_GATEWAY_ID`, `CF_API_TOKEN` | vacía, `default`, vacía | Cuenta, gateway y token de Cloudflare (el token es secreto); obligatorias con `gateway` |
| `MODEL_SMALL` | `@cf/meta/llama-3.1-8b-instruct-fast` | Modelo barato |
| `MODEL_LARGE` | `@cf/meta/llama-3.3-70b-instruct-fp8-fast` | Modelo capaz |
| `ROUTING` | `true` | Enrutamiento por pregunta |
| `ROUTER_MAX_CHARS` | `80` | Preguntas más largas van al modelo capaz |
| `HISTORY_WINDOW` | `6` | Mensajes de historial que se mandan (0: ninguno) |
| `MODEL_MAX_TOKENS` | `300` | Tope de tokens de salida |
| `MODEL_TEMPERATURE` | `0` | Con 0 las evaluaciones son repetibles |
| `CACHE_TTL_SECONDS` | `0` | Caché del gateway (0: apagada) |
| `PRICES_PATH` | `data/model_prices.json` | Precios por modelo |
| `ENVIRONMENT` | `development` | `development` o `production`; con `production` se aplican las reglas de compliance |
| `API_KEYS` | vacía | Clientes y claves, `cliente:clave,...` (secreto); vacía, todo `/ask` responde 401 |
| `RATE_LIMIT_PER_MINUTE` | `30` | Peticiones por cliente por minuto (mayor que 0) |
| `MAX_ANSWER_CHARS` | `2000` | Largo máximo de la respuesta (mayor que 0) |

`.env.example` trae todas las variables, sin valores secretos.

Un valor inválido (por ejemplo `AGENT_MAX_STEPS=0`, `SLO_P95_MS=rapido`,
`HISTORY_WINDOW=-1` o `MODEL_TEMPERATURE=tibia`) impide
arrancar, con un mensaje claro. Los booleanos aceptan `true`/`1`/`yes` y
`false`/`0`/`no`; las trazas usan esos mismos valores ya validados en `Settings`
(`create_app` construye un `Tracer` con ellos y se lo pasa al agente). La clave de
LangSmith solo se revisa en el entorno para saber si existe: no se guarda en la
configuración ni se escribe en el log.

## Estructura

- `app/`: `main.py` (`create_app()`, `ClientGuard` y `app`), `auth.py` (claves por
  cliente), `ratelimit.py` (límite por minuto), `compliance.py` (reglas de
  producción), `pii.py` (detección de PII), `guardrails.py` (inyección, secretos,
  salida y argumentos), `security.py` (evento `security`), `orchestrator.py`
  (agentes de cada petición y traza raíz), `guard.py`, `supervisor.py`,
  `reviewer.py`, `policies.py` (`search_policy`), `vacations.py` (`vacation_days`),
  `employee_ids.py` (normalización de ids), `prompts.py`, `agent.py`
  (especialistas), `completion.py` (interfaz
  `Model`, `Completion` y `ModelUnavailable`), `llm.py` (modelo simulado y
  `build_models`), `gateway.py` (cliente de AI Gateway), `routing.py` (enrutador y
  ventana), `pricing.py` (precios y costo), `directory.py`, `config.py`, `clock.py`,
  `logs.py`, `metrics.py`, `middleware.py`, `tracing.py`, `text.py` y
  `static/index.html`.
- `data/`: `employees.json`, `policies.json` (copia de `spec/policies.json`) y
  `model_prices.json`.
- `tests/`: pruebas unitarias y escenarios Gherkin.
- `doc/`: arquitectura, ADR y `compliance-checklist.md`.
