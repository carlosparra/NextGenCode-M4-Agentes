# Sesión 3 · Costos (especialistas en paralelo con un supervisor)

La fábrica agrega al producto el modelo real (Cloudflare Workers AI a través de AI Gateway) y cuatro palancas de
costo: enrutamiento, ventana de historial, tope de salida y caché. Ninguna palanca se queda si empeora la calidad:
lo decide `verification evaluate`, un programa, no un agente.

| Paso | Quién | Patrón |
| --- | --- | --- |
| Plan | `architect` y tú lo apruebas | Humano en el lazo |
| Pruebas primero | `qa-unit` | |
| Costos y pruebas e2e **al mismo tiempo** | `costs` y `qa-e2e` | **Multiagente**: supervisor con especialistas en paralelo |
| unit → contract → qa → e2e → evaluate | El supervisor decide quién corrige cada fallo (máximo 2) | Flujo con compuertas |
| Revisión contra QA.md | `qa-style` (máximo 2 vueltas) | Evaluador-optimizador |

## Preparar

Copia el producto de la sesión 2 e instala el navegador de Playwright (una vez).

macOS / Linux:

```bash
cd NextGenCode-M4-Agentes/sesion03
cp -R ../sesion02/product product
uv venv --python 3.12
uv pip install -r requirements.txt
uv run playwright install chromium
uv run python scripts/verify.py
```

Windows (PowerShell):

```powershell
cd NextGenCode-M4-Agentes\sesion03
Copy-Item -Recurse ..\sesion02\product product
uv venv --python 3.12
uv pip install -r requirements.txt
uv run playwright install chromium
uv run python scripts/verify.py
```

## Correr la fábrica

La primera vez que abres `claude` en esta carpeta te pregunta **«Do you trust the files in this folder?»**:
responde que sí. Sin esa confianza, Claude Code ignora los permisos de `.claude/settings.json` y los agentes no pueden
correr las verificaciones.

Ejecuta `claude` y, dentro, escribe `/factory`. En `output/pipeline.md` vas a ver que `costs` y `qa-e2e`
trabajaron al mismo tiempo.

## Comprobar

```bash
uv run python -m verification evaluate
uv run python -m verification e2e
```

`evaluate` imprime la calidad y el costo de la línea base y de la configuración con palancas.

Para probar con el modelo real, copia `product/.env.example` a `product/.env` y escribe tu Account ID y tu token de
Cloudflare. Nunca los pegues en el chat ni en el código. Después:

```bash
cd product
uv run --env-file .env uvicorn app.main:app
```
