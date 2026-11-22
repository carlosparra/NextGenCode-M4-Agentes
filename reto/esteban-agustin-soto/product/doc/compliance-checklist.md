# Lista de compliance

Reglas que se aplican con `ENVIRONMENT=production`. Si alguna falla, `create_app`
lanza `ValueError` y el producto no arranca. Los mensajes nombran la regla y el
cliente, nunca el valor de una clave.

| Regla | Dónde está en el código | Cómo se comprueba |
| --- | --- | --- |
| `MODEL_PROVIDER` no puede ser `fake` | `app/compliance.py`, `check_production` | `tests/test_compliance.py::test_fake_provider_is_a_violation`; escenario «Production refuses the fake model» |
| `API_KEYS` no puede estar vacía | `app/compliance.py`, `check_production` | Escenario «Production refuses an empty key list» |
| Cada clave tiene al menos 16 caracteres | `app/compliance.py`, `MIN_KEY_CHARS` | `tests/test_compliance.py::test_key_of_15_characters_fails_and_16_passes`; escenario «Production refuses a key of 15 characters» |
| Con trazas encendidas, `HIDE_INPUTS` y `HIDE_OUTPUTS` valen `true` | `app/compliance.py`, `check_production`; `app/tracing.py` | `tests/test_compliance.py::test_traces_must_hide_inputs_and_outputs`; escenario «Production refuses traces that expose the inputs» |
| `/ask` y `/metrics` exigen `X-API-Key` | `app/main.py`, `_make_require_client` | `tests/test_auth_api.py` y los escenarios de `features/production.feature` |
| Las claves se comparan en tiempo constante | `app/security.py`, `authenticate` (`hmac.compare_digest`) | `tests/test_security.py` |
| Una clave nunca se escribe en log, traza, error ni `repr` | `app/security.py` (errores con posición y largo), `app/config.py` (`repr=False`), `app/observability.py` (solo `client`) | Escenarios «The client name is logged and the key never is» y «A malformed key list does not start and does not leak»; `test_settings_repr_hides_the_keys` |
| Límite de peticiones por cliente y por minuto | `app/security.py`, `RateLimiter`; `app/main.py` | `tests/test_security.py` y los escenarios del límite (reloj inyectado) |
| La clave de la página vive en `sessionStorage` | `app/static/index.html` | Pruebas de punta a punta (`verification e2e`) |
| `PII_MASKING` vale `true`: CURP y correo se enmascaran en entrada, respuesta, log y `422` | `app/compliance.py`, `check_production`; `app/pii.py`; `app/main.py`; `app/observability.py`, `JsonLogger` | `tests/test_pii.py`, `tests/test_pii_edges.py` y `features/pii.feature`; escenario «Production refuses to start with PII masking off» |
| La documentación de la API (`/docs`, `/redoc`, `/openapi.json`) es pública a propósito porque el esquema no contiene claves, valores de configuración, CURP ni correos; `/ask` y `/metrics` siguen pidiendo clave | `app/api_docs.py` (metadatos, modelos y ejemplos con `EMP-0004`); `app/main.py`, `create_app` (`FastAPI(...)` y `secured`) | `tests/test_openapi_docs.py` |
| Los secretos no van al repositorio ni a la imagen | `.gitignore`, `.dockerignore`, `render.yaml` (`sync: false`) | `tests/test_production.py` |
| La clave de la prueba de humo es un secreto de GitHub (`SMOKE_API_KEY`) y no está en el repositorio | `.github/workflows/smoke.yml` | `tests/test_smoke_workflow.py` |
