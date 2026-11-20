APROBADO

Segunda vuelta de la revisión de QA del reto de seguridad reforzada (`spec/05-security-hardening.md`).
`uv run python -m verification qa` pasa (10.00/10); lo mecánico no se repite aquí.

## Hallazgos de la primera vuelta

### 1. El README daba instrucciones que no funcionaban con `.env`: corregido

`product/README.md`, «Cómo correrlo», ahora exporta el `.env` antes de arrancar
(`set -a; . ./.env; set +a`). También explica que la aplicación solo lee `os.environ`, que sin
ese paso todo `/ask` responde 401 y que `--env-file` necesita `python-dotenv`, que no está en
`requirements.txt`. «Cómo pedir una clave en desarrollo» remite a esa sección. Lo escrito
coincide con lo que hace `app/main.py`.

### 2. El evento `audit` escribía el nombre de herramienta que inventa el modelo: corregido

`product/app/agent.py` agrega `safe_tool_name`, que deja pasar solo los nombres de
`KNOWN_TOOLS`; cualquier otro nombre queda como `UNKNOWN_TOOL_KIND`. Se usa en `audit`, en
`security`, en el mensaje de error y en `tools_used` (que llega a `agent_run`). La traza de la
herramienta solo se abre cuando la validación ya pasó, así que siempre lleva un nombre conocido.
`tests/test_security.py::test_unknown_tool_name_never_reaches_the_log` prueba un nombre de
300 caracteres y comprueba que no aparece en ninguna línea del log.

## Incumplimientos nuevos

No encontré ningún incumplimiento grave nuevo.
