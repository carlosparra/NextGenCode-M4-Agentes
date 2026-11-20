# Reto · Producción operable: documentada, concurrente, observable, barata y segura

Parte del producto de las sesiones 1 a 4. No cambia lo que el producto hace (responder preguntas de RH): cambia
cómo se opera. Todo lo anterior sigue funcionando y sus contratos siguen pasando.

## Lo que debe hacer

1. **API documentada y sana** (`observability`).
   - `FastAPI(title="HR Assistant API", version=APP_VERSION, description=...)` con tags `chat`, `operations`.
   - Cada ruta tiene `summary` y descripción. `POST /ask` documenta sus respuestas `400`, `401`, `422`, `429` y
     `502`, con un ejemplo de cuerpo. El esquema `X-API-Key` aparece en Swagger (botón Authorize).
   - `GET /health` responde `{"status": "ok", "pid": ..., "version": APP_VERSION}`.
   - `/docs` y `/openapi.json` no piden clave y nunca contienen una clave.
2. **Concurrencia** (`observability` en el código, `deploy` en el contenedor).
   - La API sigue sin estado: el agente se crea por petición. Todo estado compartido del proceso (métricas,
     límite, caché, log) se protege con un candado (`threading.Lock`).
   - `POST /ask` sigue siendo una función normal (FastAPI la corre en su pool de hilos): no bloquea el bucle.
   - El contenedor arranca `WEB_CONCURRENCY` procesos de uvicorn (`--workers`). Las métricas, el límite y la caché
     son por proceso (ADR 0005 y 0012): `pid` en `/health` y `/metrics` dice cuál respondió.
3. **Observabilidad completa** (`observability`).
   - El evento `agent_run` agrega `latency_ms` y `cost_usd`. El evento `request` de `POST /ask` agrega `cost_usd`.
   - `GET /metrics` agrega:
     `"errors_by_status": {"4xx": n, "5xx": n}`, `"cost_usd_per_request"` (costo acumulado entre respuestas de
     `/ask`), `"security": {"auth_failures", "rate_limited", "inputs_rejected", "pii_detections",
     "outputs_blocked"}` y `"cache": {"hits", "misses"}`.
   - Las trazas de LangSmith llevan en sus metadatos `request_id`, `client`, `model`, `route`, `environment` y
     `cost_usd` (en la corrida `agent_run`), y los tags `environment` y `route`. Con `HIDE_INPUTS`/`HIDE_OUTPUTS`
     no se manda texto: solo estructura, tiempos, tokens y metadatos.
4. **Palanca 5: caché de respuestas** (`costs`).
   - Con `RESPONSE_CACHE_TTL_SECONDS` mayor que 0, una pregunta repetida (misma pregunta normalizada, mismo
     modelo elegido y misma ventana de historial) se responde desde una caché LRU en memoria de
     `RESPONSE_CACHE_SIZE` entradas, sin llamar al modelo.
   - La respuesta agrega `"cache": "hit"` o `"miss"` (el campo no aparece si la caché está apagada). Con `hit`:
     misma `answer`, `steps` y `tools_used`; `input_tokens`, `output_tokens` y `cost_usd` valen 0.
   - Nunca se guarda una respuesta si la pregunta tenía datos sensibles, ni una salida bloqueada.
   - La caché lleva su propio reloj inyectado (para el TTL) y un candado.
5. **Datos sensibles (PII)** (`guardrails`).
   - `app/pii.py` detecta, con expresiones regulares compiladas una vez: `email`, `phone` (de 7 a 10 dígitos,
     con `+52` opcional, juntos o separados por espacio, punto, guion o paréntesis: `987654321`, `5512345678`,
     `(55) 1234-5678`, `555-1234`, `+52 55 1234 5678`), `curp`, `rfc`, `card` (13 a 19 dígitos que pasan Luhn) y
     `nss` (11 dígitos). Una CURP no cuenta además como RFC; una tarjeta no cuenta como teléfono ni NSS.
     `EMP-0004` y las fechas `2019-03-04` no son PII.
   - `PII_POLICY=mask` (por omisión): en la pregunta y el historial, cada dato se reemplaza por `[EMAIL]`,
     `[TELEFONO]`, `[CURP]`, `[RFC]`, `[TARJETA]` o `[NSS]` **antes** de llegar al modelo, al log o a la traza.
     La respuesta también se enmascara antes de devolverse. La respuesta agrega `"pii_detected": [...]` con los
     tipos encontrados, sin repetir y en orden alfabético (el campo no aparece si no hubo).
   - `PII_POLICY=block`: si la pregunta o el historial tienen PII, `400 {"detail": "sensitive data not allowed"}`.
6. **Validación de entradas y salidas, y auditoría** (`guardrails`).
   - Entradas: además de Pydantic (vacía, largo), una pregunta o un mensaje del historial con inyección de
     instrucciones responde `400 {"detail": "input rejected"}`. Patrones, sin distinguir mayúsculas ni acentos:
     «ignora (todas) (las) instrucciones», «ignore (all|the) (previous|above) instructions», «prompt del
     sistema», «system prompt», «revela tus instrucciones».
   - Orden: clave (401) → límite (429) → esquema (422) → inyección (400) → PII → caché → agente → salida.
   - Salidas: antes de devolver, la respuesta se valida: no vacía (si lo está, «No encontré una respuesta.»),
     recortada a `MAX_ANSWER_CHARS`, y sin secretos (valores de `API_KEYS`, `Bearer <token>`, cadenas de 32 o más
     caracteres hexadecimales). Si trae un secreto se reemplaza por «No puedo mostrar esa respuesta.».
   - Sin datos inventados: el directorio solo tiene `id`, nombre, departamento, puesto, fecha de ingreso y
     estado. El prompt de sistema del agente le prohíbe dar cualquier otro dato de una persona (teléfono, correo,
     dirección, salario...) y le pide responder «No tengo ese dato en el directorio.». Como red de seguridad, si
     el modelo inventa un dato sensible, el enmascarado de la respuesta lo oculta (`where: answer`).
   - Auditoría: un evento `audit` con `action` en `tool_call` (ya existe), `auth_failed`, `rate_limited`,
     `input_rejected`, `pii_detected` (con `types` y `where`: `question`, `history` o `answer`) y `output_blocked`.
     Cada uno lleva `request_id` y `client` (o `null`). **Nunca** el valor detectado, la pregunta ni la clave.
   - La página muestra «Se ocultaron datos sensibles» cuando llega `pii_detected` y «Pregunta rechazada» con un
     `400`, en un elemento `data-testid="notice"`.
7. **Despliegue** (`deploy`).
   - `Dockerfile`: `CMD` con `--workers ${WEB_CONCURRENCY:-1}`; el resto igual (usuario no root, slim).
   - `render.yaml` agrega: `WEB_CONCURRENCY=2`, `RATE_LIMIT_PER_MINUTE=60`, `RESPONSE_CACHE_TTL_SECONDS=300`,
     `CACHE_TTL_SECONDS=300`, `PII_POLICY=mask`, `LANGSMITH_TRACING=true`, `LANGSMITH_PROJECT=<repositorio>` y el
     secreto `LANGSMITH_API_KEY` con `sync: false` (ahora es obligatorio: las trazas en LangSmith son requisito).
   - El CI sigue con `style → unit → e2e → docker` y `permissions: contents: read`.
8. **Documentación de decisiones** (`architect`, al final, con la tabla de `evaluate`).
   - `doc/architecture.md`: dos diagramas Mermaid (componentes y secuencia de una petición con sus guardas).
   - ADR `0014-pii-masking-before-model.md`, `0015-response-cache.md`, `0016-workers-and-per-process-state.md`.
   - `doc/observability.md`: cómo rastrear una petición por `request_id` en el log de Render y en LangSmith, qué
     mide `/metrics` y el SLO.
   - `doc/cost-analysis.md`: la tabla baseline / palancas / caché, cada palanca con su ahorro y su trade-off.
   - `doc/security.md`: tabla control / dónde está en el código / cómo se comprueba, para validación, secretos,
     auditoría, PII y mínimo privilegio (incluye permisos de los tokens de Cloudflare y LangSmith).

## Pruebas (las escribe `qa-unit`)

Entre 15 y 25 pruebas nuevas en archivos separados por área, para que cada especialista sepa cuáles son suyas:
`tests/test_reto_api.py`, `tests/test_reto_observability.py`, `tests/test_reto_costs.py`,
`tests/test_reto_guardrails.py` y `tests/features/reto.feature` con sus pasos. Las pruebas de sesiones anteriores
que comparan el conjunto exacto de campos no cambian: los campos nuevos solo aparecen cuando aplican.

## Pruebas de punta a punta (las actualiza `qa-e2e`)

- Una pregunta con un correo muestra «Se ocultaron datos sensibles» en `data-testid="notice"`.
- Una pregunta con «Ignora las instrucciones anteriores» muestra «Pregunta rechazada».

## Configuración nueva

| Variable | Por omisión | Para qué |
| --- | --- | --- |
| `APP_VERSION` | `1.0.0` | Versión en `/health` y en OpenAPI |
| `WEB_CONCURRENCY` | `1` | Procesos de uvicorn en el contenedor |
| `RESPONSE_CACHE_TTL_SECONDS` | `0` | Caché de respuestas (0: apagada) |
| `RESPONSE_CACHE_SIZE` | `256` | Entradas máximas de la caché |
| `PII_POLICY` | `mask` | `mask` o `block` |
| `MAX_ANSWER_CHARS` | `2000` | Largo máximo de la respuesta |

## Cómo se comprueba

- `verification unit`, `contract` (sesiones 1 a 4 y `test_contract_05.py`), `qa` y `e2e`.
- `verification evaluate`: baseline, palancas y palancas con caché; cada una más barata que la anterior sin
  perder calidad.
- `verification load`: 40 preguntas, 8 a la vez; ningún 5xx, 95 % o más de 200 y p95 por debajo de 5 s.
- En Render: `verification production <url>` y `verification load <url>`.