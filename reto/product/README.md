# HR Assistant

Asistente de Recursos Humanos: una API web sin estado (FastAPI) y una página que responden preguntas sobre
empleados con un agente de bucle acotado y herramientas de solo lectura (`get_employee`,
`search_by_department`). Por omisión usa un modelo simulado determinista, sin red ni costo.

Desde la sesión 2 cada petición se puede rastrear y medir:

- **`request_id`**: se toma de `X-Request-ID` si es válido (`[A-Za-z0-9._:-]`, 1 a 128) o se genera un UUID.
  Toda respuesta lo trae en el encabezado `X-Request-ID`; `POST /ask` también en el cuerpo. La página lo muestra.
- **Log JSON** en la salida estándar, una línea por evento (`request`, `agent_run`, `audit`, `error`), con `ts`,
  `service`, `event` y `request_id`. Nunca lleva el texto de preguntas ni respuestas, ni mensajes de error.
- **`GET /metrics`**: peticiones, tasa de error (5xx), latencia p50/p95, tokens y cumplimiento del SLO de este
  proceso (`pid`).
- **Trazas en LangSmith** opcionales para cada corrida del agente, llamada al modelo y herramienta.

Desde la sesión 3 cada respuesta dice qué modelo usó y cuánto costó:

- **Modelo real** con `MODEL_PROVIDER=gateway`: Cloudflare Workers AI a través de AI Gateway. Si falla, `/ask`
  responde `502 {"detail": "model unavailable", "request_id"}`.
- **Palanca 1, enrutamiento:** una regla en código manda a `MODEL_LARGE` las preguntas largas (más de
  `ROUTER_MAX_CHARS`) o con «compara», «resume», «explica», «por qué», «analiza» o «todos»; el resto va a
  `MODEL_SMALL`. Con `ROUTING=false` todo va a `MODEL_LARGE`.
- **Palanca 2, ventana de historial:** solo se mandan los últimos `HISTORY_WINDOW` mensajes.
- **Palanca 3, tope de salida:** `MODEL_MAX_TOKENS` en cada llamada.
- **Palanca 4, caché de AI Gateway:** con `CACHE_TTL_SECONDS` > 0; una respuesta `HIT` no cuesta. Está apagada por
  omisión porque el gateway guardaría respuestas con datos personales.
- **Costo:** con los precios de `data/model_prices.json` (USD por millón de tokens). Con `fake` hay dos modelos
  simulados que se llaman como `MODEL_SMALL` y `MODEL_LARGE`: responden igual y cuestan según su nombre, así que
  las palancas se miden sin red ni cuota.

Desde la sesión 4 el acceso es seguro:

- **Una clave por cliente** en `API_KEYS` (`cliente:clave,cliente2:clave2`). `POST /ask` y `GET /metrics` exigen
  el encabezado `X-API-Key`; sin clave o con una inválida responden `401 {"detail": "invalid or missing API key"}`.
  `GET /`, `GET /health` y `/docs` no la piden. El log, la auditoría y las trazas llevan solo el nombre del cliente
  (`client`), nunca la clave.
- **Límite por cliente:** más de `RATE_LIMIT_PER_MINUTE` peticiones en 60 segundos responden
  `429 {"detail": "rate limit exceeded"}` con `Retry-After` (segundos que faltan). El límite vive en la memoria
  del proceso (ADR 0012).
- **Compliance como código:** con `ENVIRONMENT=production` el producto no arranca si usa el modelo `fake`, si
  `API_KEYS` está vacía o tiene una clave de menos de 16 caracteres, o si las trazas están encendidas sin
  `HIDE_INPUTS=true` y `HIDE_OUTPUTS=true`. Las reglas y cómo se comprueban están en `doc/compliance-checklist.md`.
- **La página** tiene un campo de clave (tipo contraseña) que se guarda solo en `sessionStorage` de la pestaña.
  Con 401 muestra «Clave inválida»; con 429, «Demasiadas preguntas; espera N segundos».

La arquitectura y las decisiones están en `doc/architecture.md` y `doc/adr/`.

## Cómo correrlo

Desde la carpeta `product/`:

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Antes de arrancar define al menos un cliente en `.env` o en el entorno, por ejemplo
`API_KEYS=local:<una clave larga y aleatoria>`; sin claves la aplicación arranca en desarrollo, pero `/ask` responde
401. Abre `http://127.0.0.1:8000/` para la página y escribe la clave en su campo. Rutas:

| Ruta | Clave | Para qué |
| --- | --- | --- |
| `GET /` | No | Página web |
| `GET /health` | No | `{"status": "ok", "pid": ...}` |
| `GET /docs` | No | Documentación OpenAPI |
| `POST /ask` | Sí | `{"question", "history"}` -> `{answer, steps, tools_used, input_tokens, output_tokens, request_id, model, route, cached_calls, cost_usd}` |
| `GET /metrics` | Sí | `{pid, requests, error_rate, latency_ms: {p50, p95}, tokens: {input, output}, cost_usd, slo: {p95_ms_target, met}}` |

Ejemplo por línea de comandos (la clave se lee de una variable, no se escribe en el comando):

```bash
curl -H "X-API-Key: $HR_API_KEY" -H "Content-Type: application/json" \
  -d '{"question": "¿Quién es EMP-0004?"}' http://127.0.0.1:8000/ask
```

Para usar el modelo real, copia `.env.example` a `.env`, pon `MODEL_PROVIDER=gateway` y llena `CF_ACCOUNT_ID`,
`CF_GATEWAY_ID` y `CF_API_TOKEN` (sin ellas la aplicación no arranca). `.env` no se versiona.

Para seguir una petición en el log:

```bash
uvicorn app.main:app | jq 'select(.request_id == "demo-123")'
```

## Cómo probarlo

Desde la raíz del repositorio:

```bash
uv run python -m verification unit      # pruebas del producto, cobertura >= 80 %
uv run python -m verification contract  # contrato de las sesiones 1 a 4
uv run python -m verification qa        # pylint, 88 columnas, sin emojis, documentos
uv run python -m verification e2e       # pruebas de Playwright en product/e2e/
uv run python -m verification evaluate  # calidad y costo: línea base contra palancas
```

Ninguna prueba llama a la red: usan el modelo simulado o un `httpx.MockTransport` inyectado en lugar del gateway.
Para las pruebas de punta a punta instala el navegador una vez con `playwright install chromium`.

## Contenedor, CI y publicación

Desde la sesión 4 el producto se empaqueta en una imagen, pasa por CI y se publica en Render.

**Contenedor.** `Dockerfile` usa `python:3.12-slim`, instala `requirements.txt`, copia solo `app/` y
`data/`, y corre como un usuario sin privilegios. Escucha en `PORT` (8000 si no se define). Desde
`product/`, con la clave en una variable del entorno y no escrita en el comando:

```bash
docker build -t hr-assistant .
docker run --rm -p 8000:8000 -e PORT=8000 \
  -e API_KEYS="local:$HR_API_KEY" hr-assistant
```

Así corre con el modelo simulado en desarrollo. Para probar como en producción agrega
`-e ENVIRONMENT=production -e MODEL_PROVIDER=gateway -e CF_ACCOUNT_ID -e CF_API_TOKEN` (Docker toma el
valor de tu entorno) o usa `--env-file .env`; sin esos valores la aplicación no arranca.

**CI.** `.github/workflows/ci.yml` corre en cada `push` y `pull_request` cuatro etapas encadenadas: cada
una corre solo si la anterior pasa.

1. `style`: pylint con 88 columnas sobre `app`, `tests` y `scripts/smoke.py`.
2. `unit`: pruebas y BDD con cobertura de `app` de al menos 80 %.
3. `e2e`: arranca el producto con el modelo simulado y una clave de ejemplo que no es secreta, y corre
   Playwright.
4. `docker`: construye la imagen.

**Publicación.** `render.yaml` es el Blueprint de Render: un servicio web `hr-assistant` con la imagen
de `Dockerfile` y `healthCheckPath: /health`. Con `autoDeployTrigger: checksPass` Render despliega solo
cuando el CI pasa. Fija `ENVIRONMENT=production`, `MODEL_PROVIDER=gateway`, `HIDE_INPUTS=true` y
`HIDE_OUTPUTS=true`, así que las reglas de compliance aplican. Los secretos `API_KEYS`, `CF_ACCOUNT_ID` y
`CF_API_TOKEN` están con `sync: false`: se escriben en Render > Environment, nunca en el repositorio.
`LANGSMITH_API_KEY` es opcional y se agrega ahí mismo si se encienden las trazas.

**Prueba de humo.** Después de publicar, desde `product/`, con la clave de un cliente en `SMOKE_API_KEY`
(se lee del entorno, nunca de un argumento):

```bash
export SMOKE_API_KEY="$HR_API_KEY"
python scripts/smoke.py https://<servicio>.onrender.com
```

Comprueba que `GET /health` responde 200, `POST /ask` sin clave 401 y con clave 200; imprime `[OK]` o
`[FAIL]` en cada una y sale con 0 si todo pasa, 1 si algo falla y 2 si falta la URL o la clave.

## Variables de entorno

Todas se validan al arrancar: un valor inválido detiene la aplicación con un mensaje que nombra la variable.

| Variable | Por omisión | Para qué |
| --- | --- | --- |
| `MODEL_PROVIDER` | `fake` | Modelo a usar: `fake` (simulado) o `gateway` (Cloudflare AI Gateway) |
| `AGENT_MAX_STEPS` | `3` | Tope de vueltas del agente |
| `MAX_QUESTION_CHARS` | `2000` | Largo máximo de la pregunta y de cada mensaje del historial |
| `EMPLOYEES_PATH` | `data/employees.json` | Archivo de empleados (relativo a `product/`) |
| `SERVICE_NAME` | `hr-assistant` | Campo `service` del log |
| `SLO_P95_MS` | `2000` | Meta de latencia p95 en milisegundos (`met` si p95 < meta) |
| `LANGSMITH_TRACING` | `false` | Enciende las trazas (`true`/`false`) |
| `LANGSMITH_API_KEY` | (sin valor) | Clave de LangSmith; sin ella no hay trazas ni conexión |
| `HIDE_INPUTS` | `true` | No mandar a LangSmith las entradas |
| `HIDE_OUTPUTS` | `true` | No mandar a LangSmith las salidas |
| `CF_ACCOUNT_ID` | (sin valor) | Cuenta de Cloudflare (obligatoria con `gateway`) |
| `CF_GATEWAY_ID` | `default` | Id del AI Gateway (obligatorio con `gateway`) |
| `CF_API_TOKEN` | (sin valor) | Token de Cloudflare, secreto (obligatorio con `gateway`) |
| `MODEL_SMALL` | `@cf/meta/llama-3.1-8b-instruct-fast` | Modelo barato; debe tener precio |
| `MODEL_LARGE` | `@cf/meta/llama-3.3-70b-instruct-fp8-fast` | Modelo capaz; debe tener precio |
| `ROUTING` | `true` | Enrutamiento por pregunta (`true`/`false`) |
| `ROUTER_MAX_CHARS` | `80` | Preguntas más largas van al modelo capaz (>= 1) |
| `HISTORY_WINDOW` | `6` | Mensajes de historial que se mandan al modelo (>= 0) |
| `MODEL_MAX_TOKENS` | `300` | Tope de tokens de salida por llamada (>= 1) |
| `MODEL_TEMPERATURE` | `0` | Temperatura (0 a 2); con 0 las evaluaciones son repetibles |
| `CACHE_TTL_SECONDS` | `0` | Caché del gateway en segundos (0: apagada) |
| `PRICES_PATH` | `data/model_prices.json` | Precios por modelo en USD por millón de tokens (relativo a `product/`) |
| `ENVIRONMENT` | `development` | `development` o `production`; con `production` se aplican las reglas de compliance |
| `API_KEYS` | (vacía) | Clientes y claves, secreto: `cliente:clave,cliente2:clave2`. El nombre usa letras, dígitos, `.`, `_` o `-`; la clave se parte en el primer `:` |
| `RATE_LIMIT_PER_MINUTE` | `30` | Peticiones por cliente por minuto (>= 1) |

`.env.example` lista todas las variables sin valores secretos.

`API_KEYS` se valida al arrancar: una entrada sin `:`, con cliente o clave vacíos, con un cliente o una clave
repetidos detiene la aplicación con un mensaje que dice la posición de la entrada y su largo, nunca su valor. Las
claves no aparecen en el `repr` de la configuración, en el log, en las trazas ni en los errores, y se comparan en
tiempo constante (`hmac.compare_digest`). Genera claves largas y aleatorias, por ejemplo con
`python -c "import secrets; print(secrets.token_urlsafe(32))"`.

`LANGSMITH_API_KEY` solo se lee del entorno: la usa el SDK de LangSmith, no se guarda en la configuración y
nunca se escribe en el log ni en el código. No la pongas en archivos versionados. `CF_API_TOKEN` se guarda en la
configuración, pero no aparece en su `repr`, en el log, en las trazas ni en los mensajes de error.
