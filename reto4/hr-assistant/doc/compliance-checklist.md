# Checklist de compliance

Con `ENVIRONMENT=production`, `load_config` llama a `check_production` y, si alguna regla falla, lanza un solo
`ConfigError` con todas las reglas incumplidas: el proceso no arranca (ADR 0004 y 0011). Los mensajes nombran la
variable y, si aplica, el cliente y el largo de su clave; nunca una clave.

Además de las reglas de producción, hay controles que valen en cualquier ambiente (ADR 0009 y 0010).

| Regla | Dónde está en el código | Cómo se comprueba |
| --- | --- | --- |
| En producción `MODEL_PROVIDER` no puede ser `fake` | `app/compliance.py`, `_provider_problems` | `tests/test_compliance.py`; `tests/features/compliance.feature` (fila `MODEL_PROVIDER`) |
| En producción `API_KEYS` no puede estar vacía | `app/compliance.py`, `_api_key_problems` | `tests/features/compliance.feature` (fila `API_KEYS` vacía) |
| En producción cada clave tiene 16 caracteres o más; el error da cliente y largo, no la clave | `app/compliance.py`, `_api_key_problems` (`MIN_API_KEY_CHARS`) | `tests/test_compliance.py`; `tests/features/compliance.feature` (fila `acme:short-key-1`) |
| En producción, con `LANGSMITH_TRACING=true`, `HIDE_INPUTS` y `HIDE_OUTPUTS` valen `true` | `app/compliance.py`, `_tracing_problems` | `tests/test_compliance.py`; `tests/features/compliance.feature` (fila `HIDE_OUTPUTS`) |
| Todas las reglas incumplidas salen juntas y el producto no arranca | `app/config.py`, `_enforce_compliance` | `tests/test_compliance.py` (`load_config` con `ENVIRONMENT=production`) |
| Una configuración de producción correcta sí arranca | `app/config.py`, `_enforce_compliance` | `tests/features/compliance.feature` (escenario «Production starts with a safe configuration») |
| `ENVIRONMENT` solo admite `development` o `production` | `app/config.py`, `_environment` | `tests/test_config.py` (`ENVIRONMENT=staging`) |
| `API_KEYS` mal formada impide arrancar; el error da posición y largo, nunca el valor | `app/auth.py`, `parse_api_keys` y `_entry_error` | `tests/test_auth.py` (sin `:`, cliente o clave vacíos, coma final, repetidos) |
| Las claves no salen en `repr` de la configuración | `app/config.py` (`repr=False`) y `app/auth.py`, `ApiKeys.__repr__` | `tests/test_config.py` (`test_api_keys_never_appear_in_the_config_repr`) |
| `POST /ask` y `GET /metrics` exigen `X-API-Key`; sin clave o inválida dan `401`, antes de validar el cuerpo | `app/auth.py`, `build_require_client`; `app/main.py`, `create_app` | `tests/test_api.py`; `tests/features/security.feature` |
| Las claves se comparan con `hmac.compare_digest` contra todas, sin cortar antes | `app/auth.py`, `KeyRing.client_for` | `tests/test_auth.py` (`test_key_ring_finds_the_client_only_for_an_exact_key`) |
| `/`, `/health` y `/docs` no piden clave | `app/main.py`, `create_app` (sin la dependencia) | `tests/features/security.feature` (escenario «Public routes need no API key») |
| El log lleva `client` y nunca la clave | `app/main.py`, middleware y `_log_run` | `tests/test_api.py` (`test_client_is_logged_in_request_audit_and_agent_run`); `tests/features/security.feature` |
| La traza lleva `client` en los metadatos, nunca la clave | `app/observability.py`, `LangSmithTracer.wrap`; `app/agent.py`, `Agent._trace` | `tests/test_observability.py`; `tests/test_agent.py` |
| Más de `RATE_LIMIT_PER_MINUTE` peticiones por cliente en 60 s dan `429` con `Retry-After` | `app/ratelimit.py`, `RateLimiter.check`; `app/auth.py`, `build_require_client` | `tests/test_ratelimit.py`; `tests/test_api.py`; `tests/features/rate_limit.feature` |
| La página guarda la clave solo en `sessionStorage` y la manda en `X-API-Key` | `app/static/index.html` | `tests/features/security.feature` (campo `api-key`, la página no contiene `localStorage`); pruebas de `e2e/` |
