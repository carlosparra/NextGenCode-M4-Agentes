# Sesión 1 · Arquitectura (la fábrica construye el producto)

En esta sesión no programas. Una fábrica de agentes de Claude Code lee la especificación (`spec/`) y construye el
HR Assistant en `product/`: una API sin estado, un agente con tope de pasos, un modelo simulado y una página web.
Tú apruebas el plan y compruebas el resultado.

| Paso | Quién | Patrón |
| --- | --- | --- |
| Plan y ADR | `architect` | Razonamiento: plan y ejecución |
| Aprobar el plan | Tú | Humano en el lazo |
| Pruebas antes del código (TDD y BDD) | `qa-unit` | |
| Código | `developer` | |
| Verificación y corrección (máximo 2) | El código decide y el agente corrige | Reflexión |

El hook `hooks/permissions.py` hace que cada agente escriba solo en sus carpetas. Por ejemplo, el desarrollador no
puede tocar las pruebas.

## Preparar (una vez)

macOS / Linux:

```bash
cd NextGenCode-M4-Agentes/sesion01
uv venv --python 3.12
uv pip install -r requirements.txt
uv run python scripts/verify.py
```

Windows (PowerShell):

```powershell
cd NextGenCode-M4-Agentes\sesion01
uv venv --python 3.12
uv pip install -r requirements.txt
uv run python scripts/verify.py
```

## Correr la fábrica

La primera vez que abres `claude` en esta carpeta te pregunta **«Do you trust the files in this folder?»**:
responde que sí. Sin esa confianza, Claude Code ignora los permisos de `.claude/settings.json` y los agentes no pueden
correr las verificaciones.

```bash
claude
```

Dentro de Claude Code escribe `/factory`. La fábrica te muestra el plan y te pregunta si lo apruebas. Al terminar
deja `output/report.md` con el estado y la bitácora.

## Comprobar

```bash
uv run python -m verification unit
uv run python -m verification contract
cd product
uv run uvicorn app.main:app
```

Abre http://127.0.0.1:8000 y pregunta «¿Quién es EMP-0004?».

## Qué hay en esta carpeta

| Carpeta | Qué es |
| --- | --- |
| `spec/` | Qué debe hacer el producto (requisitos, no código) |
| `.claude/agents/` | Los agentes y sus instrucciones |
| `.claude/skills/factory/` | El orquestador `/factory` |
| `hooks/` | Permisos por agente |
| `verification/` | Pruebas de contrato: el producto visto desde afuera |
| `product/`, `output/` | Lo que generan los agentes (no se sube a git) |
