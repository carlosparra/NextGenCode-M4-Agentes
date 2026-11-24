# Checklist de compliance

Reglas que el sistema comprueba por sí mismo. Con `ENVIRONMENT=production` las cuatro
primeras impiden arrancar: el contenedor corre `python -m app.preflight` antes de uvicorn
y termina con código 1.

| Regla | Dónde está en el código | Cómo se comprueba |
| --- | --- | --- |
| En producción el modelo no puede ser el simulado | `app/config.py::check_compliance` | `test_production_compliance`; contrato del curso `test_production_refuses_the_fake_model`; `podman run -e ENVIRONMENT=production -e MODEL_PROVIDER=fake ...` termina con código 1 |
| En producción `API_KEYS` no puede estar vacía y cada clave tiene 16 caracteres o más | `app/config.py::check_compliance` | `test_production_compliance` |
| En producción, con trazas encendidas, `HIDE_INPUTS` y `HIDE_OUTPUTS` deben ser `true` | `app/config.py::check_compliance` | `test_production_compliance` |
| Con `MODEL_PROVIDER=gateway` deben existir `CF_ACCOUNT_ID`, `CF_GATEWAY_ID` y `CF_API_TOKEN` | `app/config.py::check_compliance` | `test_gateway_needs_its_credentials` |
| Un `API_KEYS` mal formado no arranca y el error no muestra la clave | `app/config.py::parse_api_keys` | `test_broken_api_keys_never_show_the_value`; contrato `test_a_broken_api_keys_never_leaks_the_key` |
| El contenedor no arranca con configuración inválida | `app/preflight.py`, `Dockerfile` (`CMD`) | `test_preflight_blocks_bad_production`; evidencia en `evidence/tests/` |
| La clave nunca se escribe en logs, trazas ni errores | `app/observability/logs.py`, `app/main.py` | `test_personal_data_never_leaves` (busca la clave en el log) |
| El texto de preguntas y respuestas nunca va al log | `app/service.py::_finish` | `test_logs_are_json_with_correlation` |
| La PII de la pregunta no llega al modelo | `app/security/guards.py::check_input` | BDD «La pregunta trae datos personales» (el modelo nunca vio el teléfono) |
| Los datos personales del directorio nunca salen | `app/domain/directory.py::public_dict` | `test_directory_hides_personal_data`, BDD «Piden un dato protegido» |
| Toda acción relevante queda auditada con cliente y `request_id` | `app/observability/logs.py::audit` | `test_injection_is_rejected_and_audited`, `test_mcp_over_http_needs_a_key_with_mcp_scope` |
| El proceso corre sin root | `Dockerfile` (`USER 10001`) | `podman exec <contenedor> id` → `uid=10001(hra)` |
| La imagen no se construye si fallan pruebas o estilo | `Dockerfile` (etapa `test`) | Construcción local con podman y en Render |
| No hay secretos en el repositorio | `.gitignore`, `.dockerignore`, `render.yaml` (`sync: false`) | Job `security` (gitleaks) en `ci.yml` |
| Dependencias sin vulnerabilidades conocidas | `requirements.txt` con versiones fijas | Job `security` (pip-audit) en `ci.yml` |
