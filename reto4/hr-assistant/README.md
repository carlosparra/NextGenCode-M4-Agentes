# HR Assistant

Asistente de Recursos Humanos que responde preguntas sobre el directorio de empleados (por id, como `EMP-0004`,
o por departamento). Es una API web sin estado (FastAPI) con una página para el personal de RH. Un agente con
bucle con tope alterna entre el modelo y dos herramientas de solo lectura.

- Sesión 1: agente, herramientas, API y página.
- Sesión 2: `X-Request-ID` en cada respuesta, log JSON por evento, `GET /metrics` y trazas opcionales en
  LangSmith.
- Sesión 3: modelo real (Cloudflare Workers AI a través de AI Gateway) y cuatro palancas de costo medibles.
- Sesión 4: una clave por cliente, límite de peticiones por cliente y reglas de compliance que se revisan al
  arrancar en producción (`doc/compliance-checklist.md`).

La arquitectura y las decisiones están en `doc/architecture.md` y `doc/adr/`.

## Cómo correrlo

Desde esta carpeta (`product/`):

```bash
pip install -r requirements.txt
uvicorn app.main:app --port 8000
```

Abre `http://127.0.0.1:8000/`. Por omisión usa el modelo simulado (`MODEL_PROVIDER=fake`), sin red ni costo.

Para preguntar hace falta una clave de cliente. Define `API_KEYS` con la forma `cliente:clave,cliente2:clave2`
(en `.env` o exportada en la terminal) y escribe tu clave en el campo «Clave de acceso» de la página. La página la
guarda solo en `sessionStorage` (se borra al cerrar la pestaña) y la manda en el encabezado `X-API-Key`. Sin
`API_KEYS` ninguna clave es válida y `/ask` responde `401`. Elige claves largas y aleatorias, por ejemplo con
`python -c "import secrets; print(secrets.token_urlsafe(24))"`, y no las escribas en el código ni en el
repositorio.

El producto lee su configuración solo de las variables de entorno: no abre ningún `.env` por su cuenta. Para el
modelo real, copia `.env.example` a `.env`, pon `MODEL_PROVIDER=gateway`, llena `CF_ACCOUNT_ID`,
`CF_GATEWAY_ID` y `CF_API_TOKEN`, y arranca pidiéndole a uvicorn que cargue ese archivo (usa `python-dotenv`,
que ya está en `requirements.txt`):

```bash
uvicorn app.main:app --env-file .env --port 8000
```

Sin `--env-file` el `.env` se ignora y sigue el modelo simulado. También puedes exportar las variables en la
terminal antes de arrancar (`export MODEL_PROVIDER=gateway` en bash, `$env:MODEL_PROVIDER="gateway"` en
PowerShell). Si falta alguna `CF_*`, el producto no arranca. El token es secreto: no lo subas al repositorio ni
lo escribas en el código.

Para ver trazas en LangSmith, pon además `LANGSMITH_TRACING=true` y `LANGSMITH_API_KEY`. Cada corrida del
agente, cada llamada al modelo y cada herramienta quedan como traza con el `request_id` en sus metadatos. Con
`HIDE_INPUTS` y `HIDE_OUTPUTS` en `true` (por omisión) no se mandan los textos de preguntas ni respuestas. Sin la
clave, el producto funciona igual y no importa `langsmith` ni se conecta.

## Pruebas

Desde la raíz del repositorio:

```bash
uv run python -m verification unit      # pruebas y cobertura (80 % o más)
uv run python -m verification contract  # contrato de las sesiones 1, 2, 3 y 4
uv run python -m verification qa        # pylint, 88 columnas, sin emojis
uv run python -m verification evaluate  # costo y calidad contra la línea base
```

Ninguna prueba llama a la red: el cliente `httpx` del modelo real se inyecta y las pruebas usan
`httpx.MockTransport`.

## API

| Ruta | Clave | Qué hace |
| --- | --- | --- |
| `GET /` | No | Página web |
| `GET /health` | No | `{"status": "ok", "pid"}` |
| `GET /docs` | No | Documentación de la API |
| `POST /ask` | Sí | `{question, history}` y devuelve `{answer, steps, tools_used, input_tokens, output_tokens, request_id, model, route, cached_calls, cost_usd}` |
| `GET /metrics` | Sí | Peticiones, `error_rate`, latencia p50/p95, tokens, SLO y `cost_usd` acumulado de este proceso |

Las rutas con clave exigen el encabezado `X-API-Key`. Ejemplo:

```bash
curl -X POST http://127.0.0.1:8000/ask -H "X-API-Key: $HR_API_KEY" \
  -H "Content-Type: application/json" -d '{"question": "¿Quién es EMP-0004?"}'
```

Errores:

- `401 {"detail": "invalid or missing API key"}` sin clave o con una inválida. Se revisa antes que el cuerpo.
- `429 {"detail": "rate limit exceeded"}` con `Retry-After` (segundos que faltan) si el cliente pasa de
  `RATE_LIMIT_PER_MINUTE` peticiones en 60 segundos. El límite es por proceso (ADR 0010): con varias copias del
  servicio se multiplica.
- `422` si la pregunta está vacía o es muy larga.
- `502 {"detail": "model unavailable", "request_id"}` si el modelo real falla.
- `500 {"detail": "internal error", "request_id"}` ante cualquier otro error.

Los eventos `request`, `audit` y `agent_run` del log, y los metadatos de las trazas, llevan el nombre del cliente
(`client`). La clave nunca se escribe en el log, en la traza ni en un mensaje de error.

## Enmascarado de PII

En `POST /ask` se reemplazan por `[<tipo> oculto]` (por ejemplo, `[email oculto]`) seis tipos de dato
personal: `email`, `curp`, `rfc`, `card` (tarjeta), `nss` y `phone` (teléfono).

- La pregunta y el historial se enmascaran antes de llegar al agente, así que no llegan al modelo ni a las
  trazas.
- La respuesta se enmascara antes de devolverla.
- La salida de las herramientas no se enmascara.

Si hubo alguna coincidencia, el log emite un evento `audit` con `action: "pii_masked"` y los conteos por tipo en
`input` (pregunta e historial) y `output` (respuesta), nunca los valores. Si no hubo ninguna, no se emite.

Falsos positivos conocidos: cualquier número de 10 dígitos se toma como teléfono y uno de 11 como NSS. Los
detalles y las alternativas están en el ADR [`doc/adr/0012-pii-masking.md`](doc/adr/0012-pii-masking.md).

## Producción y compliance

Con `ENVIRONMENT=production` el producto se niega a arrancar si:

- `MODEL_PROVIDER` es `fake`.
- `API_KEYS` está vacía o alguna clave tiene menos de 16 caracteres.
- `LANGSMITH_TRACING=true` y `HIDE_INPUTS` o `HIDE_OUTPUTS` no valen `true`.

El error lista todas las reglas incumplidas juntas y nombra la variable, el cliente y el largo de la clave, nunca
la clave. La tabla de reglas, dónde viven en el código y qué prueba las comprueba está en
`doc/compliance-checklist.md`.

## Contenedor y publicación

### Imagen de Docker

El `Dockerfile` copia solo `requirements.txt`, `app/` y `data/`, corre como un usuario sin privilegios y escucha
en `PORT` (8000 si no está definida). Ningún secreto entra en la imagen: la configuración llega solo por variables
de entorno. Desde esta carpeta (`product/`):

```bash
docker build --tag hr-assistant-alb .

# Con el modelo simulado, sin red ni costo
docker run --rm -p 8000:8000 -e API_KEYS="local:<clave>" hr-assistant-alb

# Como en producción: modelo real y reglas de compliance
docker run --rm -p 8000:8000 \
  -e ENVIRONMENT=production -e MODEL_PROVIDER=gateway \
  -e API_KEYS="cliente:<clave>" \
  -e CF_ACCOUNT_ID="<cuenta>" -e CF_GATEWAY_ID=default -e CF_API_TOKEN="<token>" \
  hr-assistant-alb
```

En lugar de varios `-e` puedes usar `--env-file .env`. Con `ENVIRONMENT=production` la imagen no arranca si se
incumple alguna regla de compliance (sección anterior); por ejemplo, una clave de menos de 16 caracteres.

### CI

`.github/workflows/ci.yml` corre en cada `push` y `pull_request`, con permiso solo de lectura. Tiene cuatro
etapas encadenadas con `needs`; si una falla, las siguientes no corren:

1. **style**: pylint sobre `app`, `tests` y `scripts` con 88 columnas y nota mínima 10.
2. **unit** (`needs: style`): pytest con cobertura de `app` de 80 % o más.
3. **e2e** (`needs: unit`): arranca el producto con el modelo simulado y una clave de ejemplo que no es secreta,
   y corre las pruebas de Playwright de `e2e/`.
4. **docker** (`needs: e2e`): construye la imagen con `docker build`.

### Publicación en Render

`render.yaml` es un Blueprint: en Render, **New > Blueprint** y elige este repositorio. Define el servicio web
`hr-assistant-alb` (Docker, plan free, `healthCheckPath: /health`) con `ENVIRONMENT=production`,
`MODEL_PROVIDER=gateway`, `CF_GATEWAY_ID=default` y `HIDE_INPUTS` / `HIDE_OUTPUTS` en `true`.

Con `autoDeployTrigger: checksPass`, Render publica cada cambio solo cuando el CI pasa.

Los secretos llevan `sync: false` y nunca se escriben en `render.yaml` ni en el repositorio. La persona los
escribe en **Render > Environment**:

- `API_KEYS`: `cliente:<clave>`, con claves de 16 caracteres o más.
- `CF_ACCOUNT_ID`: cuenta de Cloudflare.
- `CF_API_TOKEN`: token de Cloudflare.

`LANGSMITH_API_KEY` es opcional y no está en `render.yaml`: se agrega en **Render > Environment** solo si se
encienden las trazas.

### Prueba de humo

Después de publicar, desde esta carpeta (`product/`):

```bash
SMOKE_API_KEY="<clave>" python scripts/smoke.py https://<servicio>.onrender.com
```

En PowerShell: `$env:SMOKE_API_KEY="<clave>"` y luego `python scripts/smoke.py <url>`. La clave se lee solo de
`SMOKE_API_KEY`, nunca de un argumento, para que no quede en el historial, y nunca se imprime. El script imprime
`[OK]` o `[FAIL]` en cada comprobación:

- `GET /health` responde `200` (reintenta hasta 5 veces, porque Render free duerme el servicio).
- `POST /ask` sin clave responde `401`.
- `POST /ask` con clave responde `200`.

Termina con código `0` si todo pasa, `1` si algo falla y `2` si falta la URL o `SMOKE_API_KEY`.

## Palancas de costo

1. **Enrutamiento.** Una regla en código elige `MODEL_LARGE` si `ROUTING=false`, si la pregunta pasa de
   `ROUTER_MAX_CHARS` caracteres o si alguna palabra empieza con «compara», «resume», «explica», «por qué»,
   «analiza» o «todos» (sin distinguir mayúsculas ni acentos). Así «resumen» cuenta, pero «métodos» o
   «presume» no (ADR 0008). Si no, `MODEL_SMALL`. El motivo se devuelve en `route`.
2. **Ventana de historial.** Solo se mandan al modelo los últimos `HISTORY_WINDOW` mensajes del historial.
3. **Tope de salida.** `MODEL_MAX_TOKENS` en cada llamada.
4. **Caché de AI Gateway.** Con `CACHE_TTL_SECONDS > 0` se manda `cf-aig-cache-ttl`; una respuesta con
   `cf-aig-cache-status: HIT` cuenta en `cached_calls` y no cuesta.

El costo se calcula con `data/model_prices.json` (USD por millón de tokens). Con el modelo simulado hay dos
modelos que se llaman como `MODEL_SMALL` y `MODEL_LARGE`: responden igual, pero cada uno cuesta según su nombre.

## Variables

| Variable | Por omisión | Para qué |
| --- | --- | --- |
| `MODEL_PROVIDER` | `fake` | `fake` (simulado) o `gateway` (Cloudflare) |
| `AGENT_MAX_STEPS` | `3` | Tope de vueltas del agente |
| `MAX_QUESTION_CHARS` | `2000` | Largo máximo de la pregunta |
| `EMPLOYEES_PATH` | `data/employees.json` | Datos de empleados |
| `SERVICE_NAME` | `hr-assistant` | Campo `service` del log |
| `SLO_P95_MS` | `2000` | Meta de latencia p95 en milisegundos |
| `LANGSMITH_TRACING` | `false` | Enciende las trazas en LangSmith |
| `LANGSMITH_API_KEY` | vacía | Clave de LangSmith (secreta); sin ella no hay trazas |
| `HIDE_INPUTS` / `HIDE_OUTPUTS` | `true` | No mandar a LangSmith entradas ni salidas |
| `CF_ACCOUNT_ID` | vacía | Cuenta de Cloudflare |
| `CF_GATEWAY_ID` | `default` | Id del AI Gateway |
| `CF_API_TOKEN` | vacía | Token de Cloudflare (secreto) |
| `MODEL_SMALL` | `@cf/meta/llama-3.1-8b-instruct-fast` | Modelo barato |
| `MODEL_LARGE` | `@cf/meta/llama-3.3-70b-instruct-fp8-fast` | Modelo capaz |
| `ROUTING` | `true` | Enrutamiento por pregunta |
| `ROUTER_MAX_CHARS` | `80` | Preguntas más largas van al modelo capaz |
| `HISTORY_WINDOW` | `6` | Mensajes de historial que se mandan |
| `MODEL_MAX_TOKENS` | `300` | Tope de tokens de salida |
| `MODEL_TEMPERATURE` | `0` | Entre 0 y 2; con 0 las evaluaciones son repetibles |
| `CACHE_TTL_SECONDS` | `0` | Caché del gateway (0: apagada) |
| `PRICES_PATH` | `data/model_prices.json` | Precios por modelo |
| `ENVIRONMENT` | `development` | Con `production` se aplican las reglas de compliance |
| `API_KEYS` | vacía | Clientes y claves, `cliente:clave,cliente2:clave2` (secreto) |
| `RATE_LIMIT_PER_MINUTE` | `30` | Peticiones por cliente por minuto |

Si `API_KEYS` está mal formada (una entrada sin `:`, con cliente o clave vacíos, o un cliente o una clave
repetidos), el producto no arranca; el error dice qué entrada falla y su largo, nunca su valor.

Un valor inválido, un archivo de `EMPLOYEES_PATH` o `PRICES_PATH` que no existe o está mal formado, o un modelo
configurado sin precio impide arrancar, con un mensaje que nombra la variable.
