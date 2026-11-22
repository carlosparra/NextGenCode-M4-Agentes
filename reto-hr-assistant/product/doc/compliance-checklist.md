# Lista de compliance

Las reglas de producción se revisan solas: con `ENVIRONMENT=production`, `create_app` llama a
`compliance.check(settings)` antes de construir nada, y si alguna regla falla lanza `ConfigError`
y el proceso no arranca. En Render eso hace fallar el health check y se conserva la versión
anterior.

| Regla | Dónde está en el código | Cómo se comprueba |
| --- | --- | --- |
| En producción `MODEL_PROVIDER` no puede ser `fake` | `app/compliance.py`, `_provider_violations` | `tests/features/compliance.feature` (ejemplo `MODEL_PROVIDER = fake`) |
| En producción `API_KEYS` no puede estar vacía | `app/compliance.py`, `_api_key_violations` | `tests/features/compliance.feature` (ejemplo `API_KEYS = (empty)`) |
| En producción cada clave tiene 16 caracteres o más | `app/compliance.py`, `_api_key_violations` (`MIN_API_KEY_CHARS`) | `tests/features/compliance.feature` (ejemplo `API_KEYS = ops:short-key`) |
| En producción, con trazas encendidas, `HIDE_INPUTS` y `HIDE_OUTPUTS` valen `true` | `app/compliance.py`, `_tracing_violations` | `tests/features/compliance.feature` (ejemplo `HIDE_OUTPUTS = false`) |
| En producción `PII_REDACTION` vale `true` | `app/compliance.py`, `_pii_violations` | `tests/features/compliance.feature` (ejemplo `PII_REDACTION = false`) |
| Una configuración de producción segura sí arranca | `app/compliance.py`, `check`; `app/main.py`, `create_app` | `tests/features/compliance.feature` (escenario «A safe production configuration starts») |
| Las reglas se aplican al arrancar, antes de construir la app | `app/main.py`, `create_app` (primera línea después de leer la configuración) | `tests/test_compliance_steps.py` arma la app con `create_app` y espera `ConfigError` |
| `API_KEYS` mal formada impide arrancar; el error da número de entrada y largo, nunca el valor | `app/config.py`, `parse_api_keys` y `_api_keys_error` | `tests/test_config.py`, `test_malformed_api_keys_report_the_entry_and_its_length_but_never_its_value` |
| Las claves no aparecen en `repr` de la configuración | `app/config.py`, `Secret` y `Settings.api_keys` (`repr=False`) | `tests/test_config.py`, `test_api_keys_are_read_per_client_and_never_shown` |
| `POST /ask` y `GET /metrics` exigen `X-API-Key`; `/`, `/health` y `/docs` no | `app/security.py`, `build_client_guard`; `app/main.py`, rutas | `tests/features/security.feature` |
| Las claves se comparan en tiempo constante, contra todas | `app/security.py`, `ApiKeyRegistry.client_for` (`hmac.compare_digest`) | `tests/test_security.py`, `test_registry_finds_the_client_only_for_its_exact_key`; revisión de `security` |
| La clave nunca se escribe en el log, la traza ni un error; solo el `client` | `app/security.py`, `app/middleware.py`, `app/main.py`, `app/tracing.py` | `tests/features/security.feature` (claves válida e inválida ausentes del log); `tests/test_security.py`, `test_trace_metadata_names_the_client` |
| Límite por cliente con `429` y `Retry-After`, con el reloj inyectado | `app/security.py`, `RateLimiter` y `build_client_guard` | `tests/test_security.py`; `tests/features/security.feature` (escenarios del límite) |
| La página guarda la clave solo en `sessionStorage` y no trae claves escritas | `app/static/index.html` | Revisión estática de `qa-style`; pruebas e2e de `qa-e2e` |
| La pregunta y el historial se redactan antes del enrutador, el modelo, la caché, la traza y el log | `app/main.py`, `_redact_input`; `app/pii.py`, `redact` | `tests/test_pii_api.py`, `test_model_never_sees_personal_data_from_question_or_history`; `tests/features/pii.feature` |
| La respuesta del modelo pierde el HTML, se redacta y se recorta a `MAX_ANSWER_CHARS`, en ese orden; vacía da el texto de respaldo | `app/output_filter.py`, `clean_answer` | `tests/test_output_filter.py`; `tests/features/pii.feature` (escenario de la respuesta vacía) |
| `pii_detected` lleva `request_id`, `client`, `direction` y `types`, nunca el valor | `app/main.py`, `_report_pii` | `tests/test_pii_api.py`; `tests/test_output_filter.py` (el log no contiene el correo) |
| `GET /metrics` cuenta `pii_detections` por dirección y tipo, uno por tipo por evento | `app/metrics.py`, `Metrics.record_pii` | `tests/test_pii_api.py`, `test_metrics_count_each_type_once_per_detection` |
| La página no repite una pregunta con datos personales: pinta el aviso con los tipos | `app/static/index.html`, `userTurnText` | Pruebas e2e de `qa-e2e` (la página nunca muestra el correo) |
| `PII_REDACTION` y `MAX_ANSWER_CHARS` inválidos impiden arrancar | `app/config.py`, `_load_pii` | `tests/test_pii_config.py` |
| `ENVIRONMENT` solo acepta `development` o `production` | `app/config.py`, `_load_access` | `tests/test_config.py`, `test_invalid_setting_prevents_startup_naming_the_variable` |
