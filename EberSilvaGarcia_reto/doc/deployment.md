# Despliegue

## Entornos

| Entorno | Modelo | Claves | Trazas | Cómo se arranca |
| --- | --- | --- | --- | --- |
| Desarrollo | `fake` o `gateway` | Opcionales | Con texto enmascarado (opcional) | `uvicorn app.main:app --env-file .env` |
| CI | `fake` | De prueba, generadas en la corrida | No | `pytest`, `pytest e2e`, `docker build` |
| Producción (Render) | `gateway` (obligatorio) | Obligatorias, 16+ caracteres | Sin texto (obligatorio) | Imagen Docker; `preflight` antes de uvicorn |

La separación no depende de la disciplina de nadie: `ENVIRONMENT=production` activa el
compliance (ver [checklist](compliance-checklist.md)).

## Contenedor

```bash
docker build -t hr-assistant .            # etapa "test": pytest + pylint; si fallan, no hay imagen
docker run -p 8000:8000 --env-file .env hr-assistant
```

- `python:3.12-slim`, usuario `hra` (uid 10001), código propiedad de root (el proceso no
  puede modificarlo).
- `uvicorn` con `WEB_CONCURRENCY` workers (2 por omisión), `--proxy-headers` y sin la
  cabecera `Server`.
- `HEALTHCHECK` contra `/health`.

## Render

1. Haz fork de `carlosparra/NextGenCode-M4-Agentes` y sube la rama `reto`.
2. En Render: **New > Blueprint**, conecta el fork y elige la rama `reto`. En
   **Blueprint Path** escribe `EberSilvaGarcia_reto/render.yaml`.
3. Render pide los valores con `sync: false`. Escríbelos ahí, **nunca en el chat ni en
   el repositorio**:

   | Variable | Ejemplo de forma |
   | --- | --- |
   | `API_KEYS` | `portal:<clave larga>,claude:<otra clave>,grafana:<otra>` |
   | `CLIENT_SCOPES` | `portal:ask,claude:mcp,grafana:metrics` |
   | `CF_ACCOUNT_ID` | id de la cuenta de Cloudflare |
   | `CF_API_TOKEN` | token con Workers AI (Read, Edit) y AI Gateway (Run) |
   | `LANGSMITH_API_KEY` | clave de LangSmith |

   Para generar claves: `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
4. Render construye la imagen (unos minutos, porque corre las pruebas). Cuando el
   servicio esté **Live**:

   ```bash
   export SMOKE_API_KEY='<la clave de portal>'      # permiso ask
   export SMOKE_MCP_KEY='<la clave de claude>'      # permiso mcp
   export SMOKE_METRICS_KEY='<la clave de grafana>' # permiso metrics
   python scripts/smoke.py https://hr-assistant-ebersilva.onrender.com
   ```

**Si prefieres no usar Blueprint**: New > Web Service, el fork, rama `reto`, *Root
Directory* `EberSilvaGarcia_reto`, *Runtime* Docker, *Health Check Path* `/health` y las
mismas variables.

`RENDER_EXTERNAL_HOSTNAME` (lo pone Render) se agrega solo a los hosts permitidos del
MCP remoto.

## CI

`.github/workflows/ci.yml` encadena `style` → `unit` (con evaluación de costos) → `e2e`
→ `security` (gitleaks y pip-audit) → `docker`. GitHub solo ejecuta flujos de la raíz;
para activarlo en el fork, copia el archivo a `.github/workflows/` de la raíz en una rama
propia. No va en el PR porque el reto pide tocar solo esta carpeta. Mientras tanto, la
etapa `test` del Dockerfile cumple la función de compuerta en Render.

## Operación

| Tarea | Cómo |
| --- | --- |
| ¿Está vivo? | `GET /health` (Render lo usa) |
| ¿Está listo? | `GET /ready` |
| Métricas | `/dashboard`, `/metrics` o `/metrics/prometheus` con una clave `metrics` |
| Logs | Render > Logs (JSON, buscar por `request_id`) |
| Trazas | LangSmith, proyecto `hr-assistant` |
| Llamadas al modelo | Cloudflare > AI Gateway > `hr-assistant` > Logs |
| Rotar una clave | Agregar la nueva a `API_KEYS`, migrar al cliente y quitar la vieja |
| Revertir | Render > Deploys > *Rollback* al despliegue anterior |
