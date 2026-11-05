# Sesión 2 · Observabilidad (la fábrica la agrega y se observa a sí misma)

La fábrica toma el producto de la sesión 1 y le agrega lo necesario para responder «¿qué pasó con la petición X?»:
`request_id`, log JSON, auditoría, `/metrics` con SLO y trazas en LangSmith. Además, la fábrica **se observa a sí
misma**: cada herramienta de cada agente queda en una bitácora, y con ella se dibuja el pipeline de la corrida.

| Paso | Quién | Patrón |
| --- | --- | --- |
| Plan | `architect` y tú lo apruebas | Humano en el lazo |
| Pruebas primero | `qa-unit` | |
| Código | `observability` | |
| unit → contract → qa | El código decide; al primer fallo se corrige (máximo 2) | **Flujo**: encadenamiento con compuertas |
| Revisión contra QA.md | `qa-style` devuelve APROBADO o CAMBIOS (máximo 2 vueltas) | **Flujo**: evaluador-optimizador |
| Pipeline y reporte | `scripts/pipeline.py` con la bitácora | |

Hooks: `hooks/permissions.py` (cada agente escribe solo en sus carpetas) y `hooks/activity_log.py`, nuevo, que
escribe una línea en `output/activity.jsonl` por cada herramienta.

## Preparar

Copia el producto que construiste en la sesión 1.

macOS / Linux:

```bash
cd NextGenCode-M4-Agentes/sesion02
cp -R ../sesion01/product product
uv venv --python 3.12
uv pip install -r requirements.txt
uv run python scripts/verify.py
```

Windows (PowerShell):

```powershell
cd NextGenCode-M4-Agentes\sesion02
Copy-Item -Recurse ..\sesion01\product product
uv venv --python 3.12
uv pip install -r requirements.txt
uv run python scripts/verify.py
```

## Correr la fábrica

La primera vez que abres `claude` en esta carpeta te pregunta **«Do you trust the files in this folder?»**:
responde que sí. Sin esa confianza, Claude Code ignora los permisos de `.claude/settings.json` y los agentes no pueden
correr las verificaciones.

Ejecuta `claude` y, dentro, escribe `/factory`. Al terminar tendrás tres archivos:
- `output/report.md`: el estado.
- `output/qa-review.md`: la revisión de QA.
- `output/pipeline.md`: el diagrama del pipeline. Ábrelo en GitHub o en la vista previa de Markdown de tu editor.

## Comprobar

```bash
uv run python -m verification unit
uv run python -m verification contract
uv run python -m verification qa
cd product
uv run uvicorn app.main:app
```

Abre http://127.0.0.1:8000. Pregunta algo, copia el `request_id` que muestra la página y búscalo en el log de la
terminal. Luego abre http://127.0.0.1:8000/metrics.
