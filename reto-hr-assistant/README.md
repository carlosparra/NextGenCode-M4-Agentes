# Reto M4 · Sistema multiagente en producción: HR Assistant

Una **fábrica de agentes** de Claude Code (architect, qa-unit, developer, security, deploy, qa-e2e, qa-style y
triage) construye, prueba, revisa y publica el **HR Assistant**: una API con página web que responde preguntas
sobre empleados con un agente de herramientas. El reto parte del producto de la sesión 4 y le suma dos
herramientas nuevas (saldo de vacaciones y resumen por área), mínimo privilegio en los datos y una capa de
protección de datos personales (PII) en la entrada y en la salida.

| | |
| --- | --- |
| **Producción** | https://hr-as-tt35.onrender.com (`/health`, `/docs`) |
| **Repositorio que despliega Render** | `jjmoramx/hr-as` (privado; lo publica `scripts/publish.py`) |
| **Especificación del reto** | [`spec/05-reto.md`](spec/05-reto.md) |
| **Documento de entrega** (arquitectura, costos, seguridad, rúbrica) | [`docs/ENTREGA.md`](docs/ENTREGA.md) |
| **Reporte de la última corrida de la fábrica** | [`docs/reporte-fabrica.md`](docs/reporte-fabrica.md) |
| **Evidencia** (capturas) | [`docs/evidencia/`](docs/evidencia/) |

> El plan gratuito de Render apaga el servicio cuando no tiene tráfico. La primera petición puede tardar unos
> 50 segundos mientras despierta.

## Estructura

```
reto-hr-assistant/
├── spec/                  # Qué debe hacer el producto (01 a 04 de las sesiones, 05 del reto)
├── .claude/               # La fábrica: agentes, comando /factory y permisos
├── hooks/                 # permissions.py (cada agente escribe solo en lo suyo; nadie lee .env;
│                          #   nadie publica sin aprobación) y activity_log.py (bitácora)
├── verification/          # El código decide si un paso terminó bien: unit, contract, qa, e2e,
│                          #   evaluate (costo contra línea base) y production (prueba de humo)
├── scripts/               # publish.py (push al repo de Render) y pipeline.py (diagrama del pipeline)
├── tests/                 # Pruebas de la propia fábrica
├── product/               # Lo que construyen los agentes (el entregable)
│   ├── app/               # FastAPI: agente, herramientas, PII, filtro de salida, seguridad, métricas
│   ├── data/              # employees.json (ficticio) y model_prices.json
│   ├── doc/               # architecture.md, ADR 0001-0015, compliance-checklist.md
│   ├── tests/  e2e/       # Unitarias + Gherkin (126, 96.84 %) y Playwright
│   ├── Dockerfile  render.yaml  .github/workflows/ci.yml
└── docs/                  # Entrega: ENTREGA.md, reporte, plan, pipeline y evidencia
```

## Requisitos previos

- Python 3.12 y [`uv`](https://docs.astral.sh/uv/).
- Git y la CLI de GitHub (`gh`) con sesión iniciada, para publicar.
- Claude Code (plan Pro o Max), para correr la fábrica.
- Para producción: cuentas gratuitas de Render, Cloudflare (Workers AI + AI Gateway) y LangSmith.
- Docker, solo si quieres construir la imagen localmente.

## Instalación

```bash
git clone https://github.com/jjmoramx/NextGenCode-M4-Agentes.git
cd NextGenCode-M4-Agentes
git switch reto
cd reto-hr-assistant
uv venv --python 3.12
uv pip install -r requirements.txt
uv run playwright install chromium
```

## Variables de entorno

Copia `product/.env.example` a `product/.env` y completa solo lo que necesites. **Nunca subas `.env`**: está en
`.gitignore`, el hook impide que los agentes lo lean y en Render los secretos van con `sync: false`.

| Variable | Por omisión | Secreta | Para qué |
| --- | --- | --- | --- |
| `ENVIRONMENT` | `development` | | `production` activa las reglas de compliance al arrancar |
| `MODEL_PROVIDER` | `fake` | | `fake` (simulado, sin costo) o `gateway` (Workers AI) |
| `API_KEYS` | vacía | **Sí** | `cliente:clave,cliente2:clave2`. En producción, 16 caracteres o más |
| `RATE_LIMIT_PER_MINUTE` | `30` | | Peticiones por cliente por minuto (429 + `Retry-After`) |
| `PII_REDACTION` | `true` | | Redacta PII en preguntas y respuestas. Obligatoria en producción |
| `MAX_ANSWER_CHARS` | `1500` | | Largo máximo de la respuesta |
| `CF_ACCOUNT_ID` / `CF_API_TOKEN` | vacías | **Sí** | Cuenta y token de Cloudflare (permiso Workers AI) |
| `CF_GATEWAY_ID` | `default` | | ID del AI Gateway |
| `MODEL_SMALL` / `MODEL_LARGE` | Llama 3.1 8B / Llama 3.3 70B | | Modelos del enrutador |
| `ROUTING` / `HISTORY_WINDOW` / `MODEL_MAX_TOKENS` / `CACHE_TTL_SECONDS` | `true` / `6` / `300` / `0` | | Palancas de costo |
| `LANGSMITH_TRACING` / `LANGSMITH_API_KEY` / `LANGSMITH_PROJECT` | `false` / vacía / — | Clave **sí** | Trazas |
| `HIDE_INPUTS` / `HIDE_OUTPUTS` | `true` | | Las trazas no guardan preguntas ni respuestas |

Genera una clave con `python -c "import secrets; print(secrets.token_urlsafe(24))"`.

## Ejecución

### El producto en local (modelo simulado, sin cuentas)

```bash
cd product
API_KEYS="local:$(python -c 'import secrets; print(secrets.token_urlsafe(24))')" \
  uv run uvicorn app.main:app --reload
```

Abre http://localhost:8000, escribe la clave que imprimió tu `API_KEYS` (la parte después de `local:`) y pregunta
«¿Cuántos días de vacaciones le quedan a EMP-0004?». La documentación OpenAPI está en http://localhost:8000/docs.

### Las verificaciones (lo mismo que usa la fábrica)

```bash
uv run python -m verification unit       # pruebas y Gherkin con cobertura ≥ 80 %
uv run python -m verification contract   # contratos de las sesiones 1 a 4 y del reto
uv run python -m verification qa         # estilo (pylint, 88 columnas)
uv run python -m verification e2e        # Playwright contra la página
uv run python -m verification evaluate   # calidad y costo contra la línea base
```

### La fábrica completa

```bash
claude            # dentro de reto-hr-assistant; responde que sí a «Do you trust the files…»
/factory hr-as    # pide dos aprobaciones: el plan y la publicación
```

`scripts/publish.py` guarda el historial de git del producto en `output/product.git` (fuera de `product/`) y hace
push a `jjmoramx/hr-as`. Así `product/` se versiona como carpeta normal en este fork y, a la vez, Render lo
despliega desde su propio repositorio, solo si el CI pasa (`autoDeployTrigger: checksPass`).

### Prueba de humo contra producción

```bash
export SMOKE_API_KEY='<clave del cliente>'   # en tu terminal, nunca en un chat ni en un archivo
uv run python -m verification production https://hr-as-tt35.onrender.com
```

## Despliegue en Render desde cero

1. Corre la fábrica o `uv run python scripts/publish.py <repo>` (requiere `output/approved.txt`).
2. En Render: **Blueprints → New Blueprint Instance** y conecta el repositorio.
3. Escribe en Render `API_KEYS`, `CF_ACCOUNT_ID` y `CF_API_TOKEN`. Agrega `LANGSMITH_TRACING=true`,
   `LANGSMITH_API_KEY` y `LANGSMITH_PROJECT` para las trazas.
4. Cuando esté **Live**, corre la prueba de humo.
