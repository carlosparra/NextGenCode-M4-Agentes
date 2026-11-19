# Sesión 4 · Producción (la fábrica lo publica con tu aprobación)

La fábrica cierra el producto y lo publica:
- Clave por cliente, límite de peticiones y compliance como código.
- Contenedor y pipeline de CI en GitHub Actions, que los ingenieros ven etapa por etapa.
- Render, que publica solo si el pipeline pasa.

**Ningún agente publica por su cuenta.** Primero apruebas tú, y el hook lo garantiza.

| Paso | Quién | Patrón |
| --- | --- | --- |
| Plan | `architect` y tú lo apruebas | Humano en el lazo |
| Pruebas primero | `qa-unit` | |
| Seguridad, despliegue y e2e **al mismo tiempo** | `security`, `deploy` y `qa-e2e` | Supervisor con especialistas en paralelo |
| unit → contract → qa → e2e → evaluate | El supervisor decide quién corrige (máximo 2) | Flujo con compuertas |
| Revisión contra QA.md | `qa-style` (máximo 2 vueltas) | Evaluador-optimizador |
| **¿Publico?** | **Tú** | Humano en el lazo |
| GitHub, Actions y Render | `scripts/publish.py` y tú conectas Render | |
| Prueba de humo y triage (máximo 2) | `verification production` y `triage` | Enrutamiento de fallas |

El hook `hooks/permissions.py` suma dos reglas para todos, también para el orquestador:
- Nadie lee `.env`.
- Nadie corre `publish.py`, `git push` ni `gh repo create` mientras no exista `output/approved.txt`. Ese archivo solo
  lo escribe el orquestador cuando tú dices «si».

## Preparar

Copia el producto de la sesión 3.

macOS / Linux:

```bash
cd NextGenCode-M4-Agentes/sesion04
cp -R ../sesion03/product product
uv venv --python 3.12
uv pip install -r requirements.txt
uv run playwright install chromium
uv run python scripts/verify.py
```

Windows (PowerShell):

```powershell
cd NextGenCode-M4-Agentes\sesion04
Copy-Item -Recurse ..\sesion03\product product
uv venv --python 3.12
uv pip install -r requirements.txt
uv run playwright install chromium
uv run python scripts/verify.py
```

## Correr la fábrica

La primera vez que abres `claude` en esta carpeta te pregunta **«Do you trust the files in this folder?»**:
responde que sí. Sin esa confianza, Claude Code ignora los permisos de `.claude/settings.json` y los agentes no pueden
correr las verificaciones.

Ejecuta `claude` y, dentro, escribe `/factory hr-assistant`. `hr-assistant` es el nombre del repositorio que se
creará en tu cuenta de GitHub. La fábrica te pregunta dos veces: si apruebas el plan y si publica.

Después del push:

1. En GitHub, abre la pestaña **Actions** del repositorio: verás las etapas `style`, `unit`, `e2e` y `docker`.
2. En Render, entra en **New > Blueprint** y conecta el repositorio.
3. En **Render > Environment**, escribe los secretos:
   - `API_KEYS`, con la forma `hr-portal:<una clave larga>`.
   - `CF_ACCOUNT_ID` y `CF_API_TOKEN`.
   - `LANGSMITH_API_KEY` no se pide: agrégala después en Environment si enciendes las trazas.

   **Nunca los pegues en el chat.**
4. Cuando el servicio esté **Live**, define la clave en tu terminal (no en el chat) y pásale la URL a la fábrica.

macOS / Linux:

```bash
export SMOKE_API_KEY='<tu clave>'
```

Windows (PowerShell):

```powershell
$env:SMOKE_API_KEY = '<tu clave>'
```

## Comprobar

```bash
uv run python -m verification production https://<tu-servicio>.onrender.com
```

Abre la URL en el navegador, escribe tu clave en la página y pregunta «¿Quién es EMP-0004?».
