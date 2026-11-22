APROBADO

Vuelta 1 de 2 de la sesión 7. `uv run python -m verification qa` termina en `[OK] qa` (pylint 10.00/10). No hay incumplimientos claros de `QA.md`.

Lo revisado a mano:

- `product/scripts/smoke.py`: todas las funciones, públicas y privadas, traen docstring Sphinx completo (`:param`, `:type`, `:return`, `:rtype`). No hay `:raises` porque ninguna función lanza excepciones; `main` captura `httpx.HTTPError` y devuelve 1. Las líneas miden 88 columnas o menos y los nombres son claros. Las funciones son pequeñas, y los valores fijos (tiempo máximo, datos inventados, rutas documentadas) son constantes con nombre. El script no imprime la respuesta, la clave ni la dirección.
- `product/.github/workflows/smoke.yml`: no tiene claves ni direcciones escritas. La clave entra por `secrets.SMOKE_API_KEY` y la dirección por `vars.SERVICE_URL`, ambas por `env`. Solo se dispara con `workflow_dispatch` y `schedule`. Tiene `permissions: contents: read`, `timeout-minutes` y concurrencia sin cancelar. Usa las mismas versiones de las acciones que `ci.yml`.
- Documentación: `README.md`, `doc/architecture.md`, `doc/adr/0015-*.md` y `doc/compliance-checklist.md` dicen lo mismo que el código: seis comprobaciones, cron a las 13:17 UTC, secreto y variable, código de salida 2 y límites. No quedan restos de «tres comprobaciones» ni de «cinco comprobaciones». La única mención de «tres» en el ADR 0015 es histórica y describe el contexto previo. El README explica cómo crear el secreto y la variable y cómo lanzar el flujo a mano.
- Emojis: no hay ninguno en `product/`.
- Pruebas: `tests/test_smoke_script.py` usa un servidor simulado y prueba cada falla por separado. Cada caso exige exactamente un `[FAIL]`, así que no son triviales. También cubre el orden de las peticiones, que no se imprima nada sensible, el código de salida 2 y el error de red. `tests/test_smoke_workflow.py` revisa los disparadores, el secreto, los permisos, la ausencia de `set -x`, `echo`, URL y cadenas largas, y la paridad de versiones con `ci.yml`. Los nombres son claros y están en inglés.

Excepciones acordadas, no reportadas: documentación y mensajes en español, y la lógica duplicada entre `product/scripts/smoke.py` y `verification/production.py`.
