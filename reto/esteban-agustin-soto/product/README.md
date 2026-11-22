# HR Assistant

Servicio web sin estado en el que una persona pregunta por empleados o
departamentos. Un agente con bucle acotado usa dos herramientas de solo lectura
(`get_employee` y `search_by_department`) sobre `data/employees.json`. El modelo
por omisión es simulado y determinista. La sesión 2 agrega observabilidad:
un id por petición, log JSON, métricas y trazas opcionales en LangSmith.

## Cómo correrlo

```
pip install -r requirements.txt
uvicorn app.main:app --port 8000
```

Abre `http://localhost:8000/`. Las pruebas, desde la raíz del repositorio:
`uv run python -m verification unit`.

## Rutas

- `GET /`: página web (muestra el `request_id` de cada respuesta).
- `GET /health`: estado del proceso.
- `POST /ask`: `{question, history}`; responde con `request_id` en el cuerpo.
- `GET /metrics`: `pid`, `requests`, `error_rate`, `latency_ms` (p50, p95),
  `tokens` y `slo`. Son cifras de este proceso, no globales.

Toda respuesta lleva `X-Request-ID` (el recibido si es corto e imprimible, o un
UUID). Un fallo interno da `500` con `{"detail": "internal error", "request_id"}`.

## Log

Una línea JSON por evento en la salida estándar, con `ts` (UTC), `service`,
`event` y `request_id`. Eventos: `request`, `agent_run`, `audit`, `error`,
`invalid_model_output` e `invalid_tool_call`. Nunca incluye el texto de la pregunta ni de la respuesta.

`agent_run` se emite al terminar cada corrida del agente. Sus campos son
`question_chars`, `history_messages`, `steps`, `tools`, `input_tokens`,
`output_tokens`, `stopped`, `model`, `route`, `cached_calls` y `cost_usd`.
`cost_usd` es un número (USD) y es el mismo que devuelve `/ask`; sirve para
sumar el gasto desde los logs de Render. Con un modelo sin precio en el archivo
de precios hay error y el evento `agent_run` no se emite.

`invalid_model_output` se emite cuando el agente rechaza una salida del modelo.
Lleva solo `reason` (`not_json`, `not_object` o `bad_shape`), `raw_type` y
`raw_chars`, nunca el contenido.

`invalid_tool_call` se emite cuando el modelo pide una herramienta desconocida o
con argumentos que no corresponden. Lleva solo `tool` (`get_employee` o
`search_by_department` si el modelo pidió una de esas dos; en otro caso
`unknown`) y `arg_keys` (lista ordenada de las claves de los argumentos, `[]` si
faltan). Nunca incluye los valores de los argumentos, la pregunta ni el nombre
inventado de la herramienta.

En cada vuelta el agente incluye en la conversación lo que respondió el modelo
(mensaje `assistant`) antes del resultado de la herramienta. Ese resultado
termina con una instrucción fija que pide responder con `answer`.

El prompt de sistema describe las dos herramientas y sus argumentos.

El agente acepta la salida del modelo como JSON puro, con valla de Markdown, con
texto alrededor del objeto o como objeto ya parseado.

## Documentación de la API

La API se documenta sola con OpenAPI: `/docs` (Swagger UI), `/redoc` y
`/openapi.json` (el esquema). Es pública a propósito y no pide clave, porque el
esquema solo describe rutas y formas de datos: no contiene claves, valores de
configuración, CURP ni correos, y sus ejemplos usan `EMP-0004`.

Para probar `/ask` desde `/docs`:

1. Pulsa el botón *Authorize*.
2. Escribe la clave de tu cliente (`<tu-clave>`, la que está en `API_KEYS`) en
   el campo `X-API-Key` y confirma.
3. Abre `POST /ask`, pulsa *Try it out*, escribe la pregunta y pulsa *Execute*.

| Ruta | Método | Pide clave | Códigos que puede devolver |
| --- | --- | --- | --- |
| `/` | GET | No | 200 |
| `/health` | GET | No | 200 |
| `/ask` | POST | Sí | 200, 401, 422, 429, 502 |
| `/metrics` | GET | Sí | 200, 401, 429 |

`401` es `{"detail": "invalid or missing API key"}`; `422` es una pregunta vacía
o demasiado larga, o un cuerpo inválido; `429` es `{"detail": "rate limit
exceeded"}` con `Retry-After`; `502` es `{"detail": "model unavailable",
"request_id": ...}`. Un fallo interno inesperado da `500`.

## Variables de entorno

| Variable | Por omisión | Para qué |
| --- | --- | --- |
| `MODEL_PROVIDER` | `fake` | Proveedor del modelo |
| `AGENT_MAX_STEPS` | `3` | Tope de vueltas del agente |
| `MAX_QUESTION_CHARS` | `2000` | Largo máximo de la pregunta |
| `EMPLOYEES_PATH` | `data/employees.json` | Archivo de empleados |
| `SERVICE_NAME` | `hr-assistant` | Campo `service` del log |
| `SLO_P95_MS` | `2000` | Meta de latencia p95 en milisegundos |
| `LANGSMITH_TRACING` | `false` | Enciende las trazas |
| `LANGSMITH_API_KEY` | (vacía) | Clave de LangSmith; solo del entorno |
| `HIDE_INPUTS` / `HIDE_OUTPUTS` | `true` | No mandar textos a LangSmith |
| `PII_MASKING` | `true` | Enmascara CURP y correo en entradas, respuestas y logs; en producción no puede ser `false` |

Sin `LANGSMITH_API_KEY` el producto funciona igual y no se conecta.

## Costos (sesión 3)

Con `MODEL_PROVIDER=gateway` el modelo real es Cloudflare Workers AI a través
de AI Gateway; faltar `CF_ACCOUNT_ID` o `CF_API_TOKEN` impide arrancar. Con
`fake` hay dos modelos simulados con el nombre de `MODEL_SMALL` y `MODEL_LARGE`,
así el costo se mide sin red. `.env.example` lista todas las variables (token
vacío; nunca escribas un token real en el repositorio).

| Variable | Por omisión | Para qué |
| --- | --- | --- |
| `CF_ACCOUNT_ID` | (vacía) | Cuenta de Cloudflare |
| `CF_GATEWAY_ID` | `default` | Gateway de Cloudflare |
| `CF_API_TOKEN` | (vacía) | Token de Cloudflare (secreto, solo del entorno) |
| `MODEL_SMALL` | `@cf/meta/llama-3.1-8b-instruct-fast` | Modelo barato |
| `MODEL_LARGE` | `@cf/meta/llama-3.3-70b-instruct-fp8-fast` | Modelo capaz |
| `ROUTING` | `true` | Enrutamiento por pregunta (palanca 1) |
| `ROUTER_MAX_CHARS` | `80` | Preguntas más largas van al modelo capaz |
| `HISTORY_WINDOW` | `6` | Mensajes de historial que se mandan (palanca 2) |
| `MODEL_MAX_TOKENS` | `300` | Tope de tokens de salida (palanca 3) |
| `MODEL_TEMPERATURE` | `0` | Con 0 las evaluaciones son repetibles |
| `CACHE_TTL_SECONDS` | `0` | Caché del gateway, 0 la apaga (palanca 4) |
| `PRICES_PATH` | `data/model_prices.json` | Precios en USD por millón de tokens |

El enrutador es una regla en código: usa `MODEL_LARGE` si `ROUTING=false`, si la
pregunta pasa de `ROUTER_MAX_CHARS` o si contiene «compara», «resume», «explica»,
«por qué», «analiza» o «todos»; si no, `MODEL_SMALL`. Si ambos nombres son
iguales la palanca 1 no ahorra nada.

`POST /ask` agrega `model`, `route`, `cached_calls` y `cost_usd`; `/metrics`
agrega `cost_usd` acumulado. Si el gateway falla responde
`502 {"detail": "model unavailable", "request_id": ...}`. Una llamada cacheada
(`cf-aig-cache-status: HIT`) cuesta 0. Activar la caché puede servir datos de
empleados desactualizados. Un modelo sin precio en el archivo da error, no 0.
Las pruebas de punta a punta usan `pytest-playwright` (`verification e2e`).

## Acceso y producción (sesión 4)

`POST /ask` y `GET /metrics` exigen el encabezado `X-API-Key`; sin clave o con
una inválida responden `401 {"detail": "invalid or missing API key"}`. `/`,
`/health` y `/docs` no piden clave. Con `API_KEYS` vacía, `/ask` y `/metrics`
quedan cerrados (no hay acceso abierto).

| Variable | Por omisión | Para qué |
| --- | --- | --- |
| `ENVIRONMENT` | `development` | Con `production` se aplican las reglas de compliance |
| `API_KEYS` | (vacía) | `cliente:clave,cliente2:clave2` (secreto, solo del entorno) |
| `RATE_LIMIT_PER_MINUTE` | `30` | Peticiones por cliente por minuto |

- Una `API_KEYS` mal formada impide arrancar; el error dice la posición de la
  entrada y su largo, nunca su valor.
- Más peticiones por minuto que el límite dan
  `429 {"detail": "rate limit exceeded"}` con `Retry-After` (segundos que
  faltan). El conteo está en la memoria del proceso: con varios procesos o tras
  un reinicio no es exacto (ADR 0011).
- El nombre del cliente va en el log (`client`), en la auditoría y en los
  metadatos de la traza. La clave nunca se escribe.
- Con `ENVIRONMENT=production` el producto se niega a arrancar si
  `MODEL_PROVIDER=fake`, si `API_KEYS` está vacía o tiene una clave de menos de
  16 caracteres, si `PII_MASKING=false`, o si las trazas están encendidas y
  `HIDE_INPUTS` o `HIDE_OUTPUTS` no valen `true`. Ver `doc/compliance-checklist.md`.
- La página tiene un campo de clave (tipo contraseña) que se guarda en
  `sessionStorage` y se manda en `X-API-Key`. Con `401` muestra «Clave
  inválida»; con `429`, «Demasiadas preguntas; espera N segundos».

## PII: CURP y correo

La CURP y el correo que escribe una persona no vuelven a salir del servidor:
se reemplazan por `[CURP]` y `[EMAIL]` y la petición se atiende igual
(`app/pii.py`, ADR 0013). Se enmascaran la pregunta y el historial antes del
agente, el campo `answer` antes de devolverse, los valores de cada línea del log
y los datos que un `422` de validación devuelve. Cada vez que se enmascara algo
se emite un evento `audit` con `action=pii_masked`, `where` (`question`,
`history` o `answer`) y los conteos `curp` y `email`, nunca el valor. El largo de
la pregunta se valida con el texto original.

Con `PII_MASKING=false` (solo desarrollo) se apagan las tres capas; con
`ENVIRONMENT=production` el producto no arranca. No se detectan variantes
ofuscadas (espacios, guiones, «arroba»), ni se valida el dígito verificador.

## Publicación

La imagen usa Python 3.12 slim, corre con un usuario sin privilegios y escucha
en `PORT` (por omisión 8000). Los comandos se corren dentro de `product/`.

### Construir y correr la imagen

```
docker build -t hr-assistant .
docker run -p 8000:8000 \
  -e ENVIRONMENT=production \
  -e MODEL_PROVIDER=gateway \
  -e API_KEYS="<cliente>:<clave de al menos 16 caracteres>" \
  -e CF_ACCOUNT_ID="<id de la cuenta>" \
  -e CF_API_TOKEN="<token de Cloudflare>" \
  hr-assistant
```

Los valores entre `<...>` son marcadores: define los reales en tu terminal o en
un gestor de secretos, nunca los escribas en un archivo del repositorio ni en
el chat. Para probar sin Cloudflare, cambia a `ENVIRONMENT=development` y
`MODEL_PROVIDER=fake`. El servicio responde en `http://localhost:8000/health`.

### Variables en Render

`render.yaml` es el blueprint: un servicio web `hr-assistant` con Docker, plan
`free`, `healthCheckPath: /health` y `autoDeployTrigger: checksPass` (publica
solo si el CI pasa). Ya fija `ENVIRONMENT=production`, `MODEL_PROVIDER=gateway`,
`HIDE_INPUTS=true` y `HIDE_OUTPUTS=true`. Estas tres se escriben a mano en
Render > Environment (están con `sync: false`):

- `API_KEYS`: `cliente:clave,cliente2:clave2`, con claves de 16 o más
  caracteres.
- `CF_ACCOUNT_ID`: cuenta de Cloudflare.
- `CF_API_TOKEN`: token de Cloudflare.

Nunca van en el chat, en el repositorio ni en `render.yaml`.
`LANGSMITH_API_KEY` es opcional y se agrega igual en Render solo si se encienden
las trazas.

### Pipeline de CI

`.github/workflows/ci.yml` corre en cada `push` y `pull_request`. Las etapas
van en cadena y cada una necesita que la anterior pase:

1. `style`: instala dependencias y corre pylint sobre `app` y `tests` con 88
   columnas y nota mínima de 10.
2. `unit`: corre pytest sobre `tests` (pruebas y BDD) con cobertura mínima de
   80 %.
3. `e2e`: instala Chromium para Playwright, arranca el producto con el modelo
   simulado y una clave de prueba de ejemplo, y corre las pruebas de `e2e`
   contra `http://127.0.0.1:8000`.
4. `docker`: construye la imagen con `docker build -t hr-assistant .`.

### Prueba de humo

Con el servicio publicado, define la clave en el entorno (no como argumento,
para que no quede en el historial) y corre:

```
SMOKE_API_KEY=<clave> python scripts/smoke.py https://<tu-servicio>.onrender.com
```

Corre seis comprobaciones y las evalúa todas, sin cortar en la primera falla:

1. `GET /health` responde 200.
2. `GET /openapi.json` (sin clave) responde 200 y describe `/ask` y `/health`.
3. `POST /ask` sin clave responde 401.
4. `POST /ask` con clave responde 200.
5. Esa misma respuesta nombra al empleado preguntado (`EMP-0004`, Jorge Díaz) y
   no es el mensaje fijo de fallo.
6. Una pregunta con una CURP y un correo inventados responde 200 y no los
   devuelve.

Imprime `[OK]` o `[FAIL]` por cada una, solo con nombres y códigos de estado:
nunca la respuesta, la clave, la dirección ni los datos inventados. Sale con 0
si todo pasa, 1 si algo falla (o la red falla) y 2 si falta la URL o
`SMOKE_API_KEY`. Hace dos llamadas al modelo por corrida.

La fábrica tiene su propia prueba, `verification production`, que comprueba lo
mismo contra el servicio publicado desde su lado.

#### Ejecución automática (`smoke.yml`)

`.github/workflows/smoke.yml` (flujo `Smoke`) corre `scripts/smoke.py` en
GitHub Actions de dos formas: a mano (`workflow_dispatch`) y una vez al día a
las 13:17 UTC. **No** corre tras cada despliegue, ni con `push` ni con
`pull_request`: GitHub no sabe cuándo Render termina de desplegar, y una prueba
lanzada demasiado pronto fallaría contra la versión anterior. Tras publicar, se
lanza a mano.

Antes del primer uso, en GitHub (Settings > Secrets and variables > Actions):

- Pestaña *Secrets*, secreto de repositorio `SMOKE_API_KEY`: la clave de un
  cliente de `API_KEYS`. Pega el valor solo en ese campo de GitHub.
- Pestaña *Variables*, variable de repositorio `SERVICE_URL`: la dirección base
  del servicio, sin barra final (`https://<tu-servicio>.onrender.com`).

Ningún valor real se escribe en el repositorio ni en el flujo: la clave y la
dirección entran al paso solo por variables de entorno y el flujo pide el
permiso mínimo (`contents: read`).

Para lanzarlo a mano: pestaña Actions > Smoke > Run workflow, o desde la
terminal `gh workflow run smoke.yml`. Para leer el resultado, abre la corrida y
el paso «Prueba de humo»: cada comprobación aparece como `[OK]` o `[FAIL]`; si
alguna falla, la corrida termina en rojo y GitHub avisa por correo a quien la
lanzó o programó.

Límites:

- Despierta el servicio del plan free de Render, que puede tardar hasta un
  minuto; el script espera hasta 90 segundos por llamada y el trabajo tiene tope
  de 5 minutos.
- Gasta dos llamadas al modelo por corrida, es decir, unas dos al día más las
  manuales.
- GitHub desactiva los flujos programados de un repositorio tras 60 días sin
  actividad; hay que reactivarlo en la pestaña Actions.
- La variable `SERVICE_URL` no es secreta: GitHub la muestra en el encabezado
  del paso. Usa solo la dirección pública del servicio.

El diseño de la publicación está en `doc/architecture.md`.

## Más documentación

Ver `doc/architecture.md` y los ADR en `doc/adr/`.
