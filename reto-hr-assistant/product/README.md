# HR Assistant

Asistente de Recursos Humanos sin estado: responde preguntas sobre empleados y departamentos con un
agente que alterna entre un modelo de lenguaje y dos herramientas de solo lectura (`get_employee` y
`search_by_department`). El historial de la conversación vive en el navegador; la API no guarda nada
entre peticiones.

Cada petición deja datos para responder "¿qué pasó con la petición X?": un id por petición, un log
JSON por evento, métricas del proceso y, opcionalmente, trazas en LangSmith.

Cada respuesta dice qué modelo la dio y cuánto costó. El modelo real es Cloudflare Workers AI a
través de AI Gateway; cuatro palancas (enrutamiento, ventana de historial, tope de salida y caché)
bajan el costo sin bajar la calidad.

## Cómo correrlo

Desde la carpeta `product/`:

```bash
pip install -r requirements.txt
uvicorn app.main:app --port 8000
```

Por omisión usa el modelo simulado (`MODEL_PROVIDER=fake`): no llama a la red ni gasta cuota.

El producto lee la configuración solo de las variables de entorno: no carga ningún archivo
`.env` por su cuenta. Para usar uno, expórtalo en la misma terminal antes de arrancar:

```bash
cp .env.example .env   # ajusta las variables; con gateway llena las CF_*
set -a; . ./.env; set +a
uvicorn app.main:app --port 8000
```

`set -a` exporta cada variable que define `.env`; sin ese paso uvicorn arranca con los valores
por omisión (por ejemplo, `MODEL_PROVIDER=fake`) aunque el archivo exista.

`POST /ask` y `GET /metrics` piden una clave. Con `API_KEYS` vacía toda pregunta responde `401`
(falla cerrado). Para probar en local, genera una clave y ponla en `API_KEYS` de tu `.env`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(24))"
# en .env: API_KEYS=local:<la clave que salió>
```

Abre `http://localhost:8000/`, escribe la clave en el campo «Clave de acceso» y pregunta. Bajo cada
respuesta aparece `Id de la petición: <request_id>`; ese es el dato que se pasa a soporte.

Pruebas (desde la raíz del repositorio):

```bash
uv run python -m verification unit
uv run python -m verification contract
uv run python -m verification qa
uv run python -m verification evaluate
uv run python -m verification e2e
```

`e2e` arranca el producto y corre las pruebas de Playwright de `e2e/` en un navegador. Necesita
`pytest-playwright` (ya está en el `requirements.txt` de la raíz) y, la primera vez, el
navegador: `uv run playwright install chromium`.

`evaluate` corre el set de evaluación con el modelo simulado dos veces (línea base con
`ROUTING=false` y sin ventana, y con las palancas por omisión) y pasa solo si la calidad no baja y
el costo sí baja.

## Rutas

| Ruta | Clave | Qué hace |
| --- | --- | --- |
| `GET /` | no | Página web con el formulario |
| `GET /health` | no | `{"status": "ok", "pid": ...}` |
| `GET /docs` | no | Documentación de la API |
| `POST /ask` | sí | `{question, history}` y devuelve `answer`, `steps`, `tools_used`, tokens, `request_id`, `model`, `route`, `cached_calls`, `cost_usd` y `pii_redacted` |
| `GET /metrics` | sí | Métricas de este proceso (ver abajo) |

## Acceso por clave y límite de peticiones

- Cada cliente tiene su clave en `API_KEYS` (`cliente:clave,cliente2:clave2`) y la manda en el
  encabezado `X-API-Key`. Sin clave o con una inválida: `401 {"detail": "invalid or missing API key"}`.
- Las claves se comparan con `hmac.compare_digest` contra todas las del registro. Solo el nombre
  del cliente (`client`) llega al log, a la auditoría y a los metadatos de la traza; la clave nunca
  se escribe en el log, la traza ni un mensaje de error.
- Si `API_KEYS` está mal formada (entrada sin `:`, cliente o clave vacíos, cliente o clave
  repetidos) el producto no arranca; el error dice el número de la entrada y su largo, nunca su
  valor.
- Cada cliente puede hacer `RATE_LIMIT_PER_MINUTE` peticiones en cualquier ventana de 60 segundos.
  La siguiente responde `429 {"detail": "rate limit exceeded"}` con `Retry-After` (segundos que
  faltan, redondeados hacia arriba, mínimo 1). Los rechazos no ocupan cupo. El límite usa el reloj
  inyectado y vive en la memoria de cada proceso: con varias copias, cada una cuenta el suyo.
- La página guarda la clave en `sessionStorage` (se borra al cerrar la pestaña) y la manda en
  `X-API-Key`. Con `401` muestra «Clave inválida»; con `429`, «Demasiadas preguntas; espera N
  segundos».

## Protección de datos personales (PII)

- Con `PII_REDACTION=true` (por omisión), `app/pii.py` busca en la pregunta y en cada turno del
  historial correos, teléfonos de 10 dígitos (con o sin espacios, guiones o `+52`), CURP, RFC con
  homoclave y tarjetas de 13 a 19 dígitos que pasan Luhn, y los reemplaza por `[EMAIL]`,
  `[PHONE]`, `[CURP]`, `[RFC]` o `[CARD]` antes del enrutador. El modelo, la caché, la traza y el
  log nunca ven el valor original. Los ids `EMP-0000` y las fechas no son PII.
- La respuesta sigue siendo `200`; `pii_redacted` lista los tipos encontrados en la pregunta (por
  ejemplo `["EMAIL"]`), nunca los valores. Lista vacía si no hubo.
- La respuesta del modelo pasa por `app/output_filter.py` en este orden: quita etiquetas HTML,
  redacta PII y recorta a `MAX_ANSWER_CHARS`. Si queda vacía se responde «No tengo una respuesta
  para eso.». Con `PII_REDACTION=false` no se redacta, pero el HTML y el recorte se aplican igual.
- Cada detección escribe `pii_detected` en el log y suma a `pii_detections` en `/metrics`.
- La página pinta el turno de la persona solo después del `200`; si `pii_redacted` no está vacío,
  muestra «Tu pregunta tenía datos personales que se ocultaron: EMAIL» en lugar del texto.

## Compliance en producción

Con `ENVIRONMENT=production` el producto se niega a arrancar si `MODEL_PROVIDER=fake`, si
`API_KEYS` está vacía o alguna clave tiene menos de 16 caracteres, si `LANGSMITH_TRACING=true` y
`HIDE_INPUTS` o `HIDE_OUTPUTS` no valen `true`, o si `PII_REDACTION` no vale `true`. El detalle de
cada regla está en
[`doc/compliance-checklist.md`](doc/compliance-checklist.md).

Toda respuesta, incluidas las `401`, `422`, `429`, `500` y `502`, trae el encabezado
`X-Request-ID`. Si el cliente
lo manda con 1 a 128 caracteres `[A-Za-z0-9._-]` se respeta; si no, se genera un UUID4. Un error
inesperado responde `500 {"detail": "internal error", "request_id": ...}`; si el modelo no responde,
`502 {"detail": "model unavailable", "request_id": ...}`.

## Costos

- **Modelo real** (`MODEL_PROVIDER=gateway`): llama a
  `https://gateway.ai.cloudflare.com/v1/{CF_ACCOUNT_ID}/{CF_GATEWAY_ID}/workers-ai/v1/chat/completions`
  con `Authorization: Bearer {CF_API_TOKEN}`. Sin alguna de las tres variables `CF_*` no arranca.
  Los tokens salen de `usage.prompt_tokens` y `usage.completion_tokens`.
- **Enrutamiento** (`ROUTING`): una regla en código manda a `MODEL_LARGE` las preguntas de más de
  `ROUTER_MAX_CHARS` caracteres o con «compara», «resume», «explica», «por qué», «analiza» o
  «todos» (sin distinguir mayúsculas ni acentos); el resto va a `MODEL_SMALL`. `route` dice el
  motivo: `routing_disabled`, `long_question`, `keyword:<palabra>` o `default_small`. Se buscan
  palabras completas sobre el texto normalizado, así que «resumen» no activa «resume» y las
  preguntas de `department_summary` van al modelo barato (el cálculo lo hace el código).
- **Ventana de historial** (`HISTORY_WINDOW`): al modelo solo van los últimos mensajes; con `0`,
  ninguno.
- **Tope de salida** (`MODEL_MAX_TOKENS`) en cada llamada, con `MODEL_TEMPERATURE`.
- **Caché de AI Gateway** (`CACHE_TTL_SECONDS` mayor que 0): se manda `cf-aig-cache-ttl`; una
  respuesta con `cf-aig-cache-status: HIT` cuenta en `cached_calls` y no cuesta.
- **Precio**: `cost_usd` se calcula con `PRICES_PATH` (USD por millón de tokens). Si `MODEL_SMALL`
  o `MODEL_LARGE` no tienen precio, no arranca. Con `fake` hay dos modelos simulados con esos mismos
  nombres: responden igual, pero cuestan según su nombre, así que las palancas se miden sin red.

## Log

Una línea JSON por evento en la salida estándar, con `ts` (ISO 8601 en UTC), `service`, `event` y
`request_id` primero:

- `request`: `method`, `path`, `status`, `latency_ms` (uno por petición) y `client` cuando la
  clave es válida.
- `agent_run`: `client`, `question_chars`, `history_messages`, `history_sent`, `model`, `route`, `steps`,
  `tools`, `input_tokens`, `output_tokens`, `cached_calls`, `cost_usd` y `stopped` (`answer` o
  `max_steps`). Nunca el texto de la pregunta ni de la respuesta.
- `audit`: uno por herramienta, con `client`, `action: "tool_call"`, `tool` y `args`.
- `error`: `error_type` con el tipo de la excepción, nunca su mensaje.
- `pii_detected`: `client`, `direction` (`input` u `output`) y `types`. Nunca el valor detectado.

Para seguir una petición: filtra el log por su `request_id`.

## Métricas

`GET /metrics` devuelve `pid`, `requests`, `error_rate` (respuestas `>= 500`), `latency_ms.p50` y
`latency_ms.p95` (rango más cercano sobre las últimas 1000 peticiones), `tokens.input`,
`tokens.output`, `cost_usd` acumulado y `slo` (`p95_ms_target` y `met`, que es `true` si el p95 está por debajo de
`SLO_P95_MS`) y `pii_detections`, con un conteo por dirección y por tipo (uno por tipo por
evento, por ejemplo `{"input": {"EMAIL": 2}, "output": {}}`). Son contadores de este proceso: se pierden al reiniciar y cada copia reporta los
suyos con su `pid`. Cuentan todas las rutas, incluidas `/health` y `/metrics`, que suelen ser
rápidas y bajan el p95.

## Variables de entorno

| Variable | Por omisión | Para qué |
| --- | --- | --- |
| `MODEL_PROVIDER` | `fake` | Proveedor del modelo: `fake` (determinista) o `gateway` |
| `AGENT_MAX_STEPS` | `3` | Tope de vueltas del agente |
| `MAX_QUESTION_CHARS` | `2000` | Largo máximo de la pregunta y de cada turno |
| `EMPLOYEES_PATH` | `data/employees.json` | Archivo de empleados (relativo a `product/`) |
| `SERVICE_NAME` | `hr-assistant` | Campo `service` del log |
| `SLO_P95_MS` | `2000` | Meta de latencia p95 en milisegundos (entero mayor que 0) |
| `LANGSMITH_TRACING` | `false` | Enciende las trazas (`true` o `false`) |
| `LANGSMITH_API_KEY` | (sin valor) | Clave de LangSmith; sin ella no hay trazas |
| `HIDE_INPUTS` / `HIDE_OUTPUTS` | `true` | No mandar a LangSmith entradas ni salidas |
| `CF_ACCOUNT_ID` | (sin valor) | Cuenta de Cloudflare |
| `CF_GATEWAY_ID` | `default` | Gateway de AI Gateway |
| `CF_API_TOKEN` | (sin valor) | Token de Cloudflare (secreto) |
| `MODEL_SMALL` | `@cf/meta/llama-3.1-8b-instruct-fast` | Modelo barato |
| `MODEL_LARGE` | `@cf/meta/llama-3.3-70b-instruct-fp8-fast` | Modelo capaz |
| `ROUTING` | `true` | Enrutamiento por pregunta |
| `ROUTER_MAX_CHARS` | `80` | Preguntas más largas van al modelo capaz |
| `HISTORY_WINDOW` | `6` | Mensajes de historial que se mandan (0 o más) |
| `MODEL_MAX_TOKENS` | `300` | Tope de tokens de salida |
| `MODEL_TEMPERATURE` | `0` | Temperatura (número mayor o igual que 0) |
| `CACHE_TTL_SECONDS` | `0` | Caché del gateway en segundos (0: apagada) |
| `PRICES_PATH` | `data/model_prices.json` | Precios por modelo (relativo a `product/`) |
| `ENVIRONMENT` | `development` | `development` o `production`; con `production` se aplican las reglas de compliance |
| `API_KEYS` | (sin valor) | Clientes y claves, `cliente:clave,cliente2:clave2` (secreto) |
| `RATE_LIMIT_PER_MINUTE` | `30` | Peticiones por cliente por minuto (entero mayor que 0) |
| `PII_REDACTION` | `true` | Redacta PII en preguntas y respuestas (`true` o `false`). En producción es obligatoria |
| `MAX_ANSWER_CHARS` | `1500` | Largo máximo de la respuesta que llega al cliente (entero mayor que 0) |

Un valor inválido impide arrancar y el mensaje nombra la variable (nunca el valor del token).
Lo mismo pasa si `EMPLOYEES_PATH` o `PRICES_PATH` apuntan a un archivo que no existe o que no
tiene el formato esperado.
`.env.example` trae todas las variables, con los secretos vacíos.

## Trazas en LangSmith (opcional)

Con `LANGSMITH_TRACING=true` y `LANGSMITH_API_KEY` en el entorno, la corrida del agente, cada
llamada al modelo y cada herramienta quedan como trazas, con el `request_id` y el `client` en sus
metadatos. Sin
la clave el producto funciona igual y ni siquiera importa `langsmith`. La clave se lee solo del
entorno: no se guarda en la configuración ni se escribe en el log.

## Contenedor y publicación

El `Dockerfile` arma una imagen sobre `python:3.12-slim` que corre como un usuario sin privilegios (`appuser`). Solo copia `requirements.txt`, `app/` y `data/`. El `.dockerignore` deja fuera `.env` y `.env.*`, las pruebas, las cachés, la documentación y los archivos de CI y de despliegue. El contenedor escucha en `PORT` (8000 si no se define).

Desde la carpeta `product/`:

```bash
docker build -t hr-assistant .
docker run --rm -p 8000:8000 -e PORT=8000 \
  -e API_KEYS=local:ejemplo-no-secreto-0123456789 hr-assistant
```

La clave del ejemplo es inventada. Para pruebas locales genera la tuya (ver «Cómo correrlo») y no la escribas en archivos versionados. Sin `MODEL_PROVIDER`, la imagen usa el modelo simulado.

### CI

`.github/workflows/ci.yml` corre en cada `push` y `pull_request` con cuatro trabajos encadenados. Si uno falla, los siguientes no corren:

1. `style`: pylint sobre `app`, `tests` y `scripts/smoke.py`, con líneas de máximo 88 columnas.
2. `unit`: `pytest tests` con cobertura mínima de 80 % sobre `app`.
3. `e2e`: arranca el producto con el modelo simulado y una clave de ejemplo, espera a que `/health` responda y corre las pruebas de Playwright de `e2e/`.
4. `docker`: construye la imagen, la arranca con el modelo simulado y comprueba que `/health` responda.

### Publicación en Render

`render.yaml` es un Blueprint de Render. Define un servicio web `hr-as` (plan `free`, rama `main`) que se construye con el `Dockerfile` y usa `/health` como chequeo de salud. Fija `ENVIRONMENT=production`, `MODEL_PROVIDER=gateway`, `HIDE_INPUTS=true` y `HIDE_OUTPUTS=true`, así que se aplican las reglas de «Compliance en producción».

Los secretos `API_KEYS`, `CF_ACCOUNT_ID` y `CF_API_TOKEN` están marcados con `sync: false`. No van en el repositorio: se escriben en Render > Environment al crear el Blueprint. `LANGSMITH_API_KEY` es opcional y se agrega en el mismo lugar si hace falta.

Con `autoDeployTrigger: checksPass`, Render publica solo cuando el CI pasa completo (`style`, `unit`, `e2e` y `docker`).

### Prueba de humo

Después de publicar, desde la carpeta `product/`:

```bash
SMOKE_API_KEY=<clave> python scripts/smoke.py https://<servicio>.onrender.com
```

Comprueba tres cosas: `GET /health` responde `200`, `POST /ask` sin clave responde `401` y `POST /ask` con clave responde `200`. Imprime `[OK]` o `[FAIL]` por cada una y termina con `0` solo si pasan las tres (`1` si algo falla, `2` si el uso es incorrecto). La clave se lee solo de `SMOKE_API_KEY`, nunca de un argumento, para que no quede en el historial de la terminal. Espera hasta 90 segundos por petición, porque Render puede tardar en despertar un servicio dormido.

## Estructura

- `app/config.py`: lee y valida las variables.
- `app/clock.py`: reloj inyectable (único lugar que lee la hora real).
- `app/logs.py`: log JSON.
- `app/metrics.py`: métricas del proceso.
- `app/middleware.py`: id por petición, evento `request`, errores y encabezado.
- `app/tracing.py`: trazas opcionales.
- `app/security.py`: claves por cliente, límite por minuto y la dependencia que responde `401`/`429`.
- `app/compliance.py`: reglas de producción que se revisan al arrancar.
- `app/pii.py`: detector y redacción de PII (solo expresiones regulares y Luhn).
- `app/output_filter.py`: filtro de la respuesta (HTML, PII, recorte y texto de respaldo).
- `app/agent.py`, `app/llm.py`, `app/directory.py`: agente, modelos y datos.
- `app/model_reply.py`: respuesta común de los modelos (texto, tokens y si fue de caché).
- `app/gateway.py`: modelo real en AI Gateway con `httpx` (cliente inyectable).
- `app/routing.py`: enrutador y ventana de historial.
- `app/pricing.py`: tabla de precios y costo por respuesta.
- `app/main.py`: arma la aplicación.
- `data/model_prices.json`: precios por modelo en USD por millón de tokens.
- `tests/`: pruebas unitarias (sin red).
- `e2e/`: pruebas de punta a punta con Playwright contra el producto corriendo.
- `Dockerfile`: imagen del producto con usuario sin privilegios; escucha en `PORT`.
- `.dockerignore`: deja fuera de la imagen secretos, pruebas, cachés, CI y documentación.
- `.github/workflows/ci.yml`: CI con cuatro trabajos encadenados (style, unit, e2e y docker).
- `render.yaml`: Blueprint de Render; publica solo si el CI pasa y deja los secretos en `sync: false`.
- `scripts/smoke.py`: prueba de humo contra el servicio publicado (`/health`, `401` sin clave y `200` con clave).
