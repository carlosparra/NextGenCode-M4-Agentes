# Despliegue

## Contenedor

```bash
docker build -t hr-assistant .
docker run --rm -p 8000:8000 --env-file .env hr-assistant
```

El `Dockerfile` tiene tres etapas:

1. `base`: `python:3.12-slim` con las dependencias de `requirements.txt`, fijadas por
   versión para que la construcción sea reproducible.
2. `test`: instala las dependencias de desarrollo y corre las pruebas (cobertura de
   90 % o más) y pylint. Si algo falla, la construcción se detiene.
3. `runtime`: solo `app/` y `data/`. Depende de un marcador de la etapa `test`, corre
   con el usuario `hr` y no puede escribir en `/srv`.

Al arrancar corre `python -m app.preflight`; si la configuración es insegura, termina
con código 1 y un mensaje que dice qué regla falla.

## Render

`render.yaml` es un Blueprint con un servicio web en el plan gratuito.

1. En Render: **New > Blueprint** y conecta el fork `NextGenCode-M4-Agentes`.
2. Rama: `reto`. Ruta del Blueprint: `AlbertoRayon_reto/render.yaml`.
3. Render pide los secretos. Escríbelos ahí, nunca en un chat:

   | Variable | Valor |
   | --- | --- |
   | `API_KEYS` | `portal:<clave>,claude:<clave>,grafana:<clave>`, cada clave de 16 caracteres o más |
   | `CF_ACCOUNT_ID` | Account ID de Cloudflare (32 caracteres) |
   | `CF_API_TOKEN` | Token con permiso de Workers AI |
   | `LANGSMITH_API_KEY` | Clave de LangSmith |

4. Cuando el servicio esté **Live**, corre la prueba de humo con las claves en
   variables de entorno:

   ```bash
   export SMOKE_API_KEY='<clave de portal>'
   export SMOKE_MCP_KEY='<clave de claude>'
   export SMOKE_METRICS_KEY='<clave de grafana>'
   python scripts/smoke.py https://<servicio>.onrender.com
   ```

Para generar claves largas sin que pasen por la pantalla:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))" | wl-copy
```

### Workers AI directo o vía AI Gateway

| `MODEL_PROVIDER` | Cómo llama | Qué necesita | Qué da de más |
| --- | --- | --- | --- |
| `workers` | Directo a Workers AI | Token con permiso de Workers AI | Nada: es el camino mínimo |
| `gateway` | A través de AI Gateway | Además, un gateway (`CF_GATEWAY_ID`, por omisión `default`) y permiso para usarlo | Caché (`CACHE_TTL_SECONDS`) y analítica del gateway |

El Blueprint publica con `workers`, porque el token con el que se probó no tiene
permiso de AI Gateway (la llamada vía gateway responde `401`, código 2009). Para
pasar a `gateway`:

1. En Cloudflare, entra a **AI > AI Gateway** y comprueba que exista el gateway
   `default`; si no, créalo.
2. Si el gateway es autenticado, crea un token con el permiso **AI Gateway: Run** y
   ponlo en `CF_AIG_TOKEN` (o agrega ese permiso al token de `CF_API_TOKEN`).
3. Cambia `MODEL_PROVIDER` a `gateway` en Render > Environment.

### Detalles a tener en cuenta

- `CLIENT_SCOPES` ya viene en el Blueprint: `portal:ask,claude:mcp,grafana:metrics`.
  Los nombres de cliente de `API_KEYS` deben coincidir, o el servicio no arranca.
- Si tu cuenta de LangSmith es EU, agrega `LANGSMITH_ENDPOINT`.
- Render define `RENDER_EXTERNAL_HOSTNAME`; la aplicación lo agrega solo a los hosts
  permitidos del MCP remoto.
- El plan gratuito duerme el servicio tras 15 minutos sin uso; la primera petición
  después tarda cerca de un minuto.
- `autoDeployTrigger: commit`: Render publica en cada push a `reto`. La compuerta es
  la etapa `test` del `Dockerfile` (ver ADR 0006).

## Otros entornos

La imagen no depende de Render: corre igual en Cloud Run, ECS o Azure Container Apps.
Solo necesita las variables de entorno y que la plataforma defina `PORT`.

## Rotar un secreto sin tumbar el servicio

1. Crea el secreto nuevo en el proveedor.
2. Cámbialo en Render > Environment y espera a que el servicio vuelva a estar Live.
3. Revoca el secreto viejo.
