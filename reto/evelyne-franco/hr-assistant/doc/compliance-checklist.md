# Checklist de compliance

Reglas de seguridad del HR Assistant (`spec/04-production.md`, puntos 1 a 4, y
`spec/05-security-hardening.md`, puntos 1 a 9, en la segunda tabla). Las tres
primeras filas se revisan solas al arrancar con `ENVIRONMENT=production`:
`create_app` llama a `compliance.enforce`, que lanza `ComplianceError` con el nombre de
cada regla que falla y nunca con un valor. El resto se aplica en cada petición.

La vista completa de todos los controles (también los de observabilidad, despliegue y
navegador), con sus trade-offs, está en `doc/security.md`. La decisión sobre PII y
validación de salidas está en el ADR 0013.

Cada prueba se corre con `uv run python -m verification unit`. Los escenarios están en
`tests/features/production.feature` y sus pasos en `tests/test_production_steps.py`.

| Regla | Dónde está en el código | Cómo se comprueba |
| --- | --- | --- |
| En producción `MODEL_PROVIDER` no puede ser `fake` | `app/compliance.py`: `production_violations` (`RULE_REAL_MODEL`) y `enforce`, llamado al inicio de `app/main.py:create_app` | Escenario «Production refuses to start with unsafe settings» (`the fake model`); `tests/test_compliance.py::test_every_production_violation_is_reported_without_values`; contrato `test_production_refuses_the_fake_model` |
| En producción `API_KEYS` no está vacía y cada clave tiene 16 caracteres o más | `app/compliance.py`: `_has_strong_keys` (`RULE_STRONG_KEYS`, `MIN_KEY_CHARS`) | Escenario «Production refuses to start with unsafe settings» (`no API keys` y `a key shorter than 16 characters`); `tests/test_compliance.py` |
| En producción, con trazas encendidas, `HIDE_INPUTS` y `HIDE_OUTPUTS` valen `true` | `app/compliance.py`: `_hides_traced_data` (`RULE_HIDDEN_TRACES`) | Escenario «Production refuses to start with unsafe settings» (`traces that show the inputs`); `tests/test_compliance.py` |
| Fuera de producción no hay reglas de arranque | `app/compliance.py`: `production_violations` devuelve `[]` si `environment` no es `production` | `tests/test_compliance.py::test_development_has_no_compliance_rules`; escenario «A well configured production starts and accepts its key» |
| `POST /ask` y `GET /metrics` exigen `X-API-Key`; sin clave o con una inválida responden `401 {"detail": "invalid or missing API key"}` | `app/main.py`: `ClientGuard.__call__`, usado como dependencia en `ask` y `metrics_snapshot` | Escenario «A request without a valid key is rejected»; `tests/test_main.py`; contrato `test_asking_without_a_key_returns_401` y `test_asking_with_a_wrong_key_returns_401` |
| `GET /`, `GET /health` y `/docs` no piden clave | `app/main.py`: `_add_open_routes` (sin `ClientGuard`); `/docs` lo sirve FastAPI | Escenario «The page, the health check and the docs need no key»; contrato `test_health_and_page_need_no_key` |
| Las claves se comparan con `hmac.compare_digest`, contra todas las configuradas | `app/auth.py`: `ApiKeyAuth.client_for` | `tests/test_auth.py::test_each_key_maps_to_its_client_and_unknown_keys_to_none` |
| `API_KEYS` mal formada impide arrancar; el error dice la entrada y su largo, nunca su valor | `app/auth.py`: `parse_api_keys`, `_parse_entry` y `_malformed`; se llama desde `app/config.py:_production_values`, fuera de Pydantic | `tests/test_auth.py::test_malformed_entry_error_names_its_position_and_length_but_never_its_value`; `tests/test_config.py::test_api_keys_never_appear_in_settings_or_startup_errors`; contrato `test_a_broken_api_keys_never_leaks_the_key` (busca la clave en `stderr`) |
| La clave nunca se escribe en la configuración, el log, la traza ni un error | `app/auth.py`: `ApiKey.key` es `SecretStr`; `app/main.py:ClientGuard` solo guarda `client` en `scope["state"]`; `app/middleware.py` nunca lee `X-API-Key` | `tests/test_config.py::test_api_keys_never_appear_in_settings_or_startup_errors`; escenarios con «the key that was sent appears nowhere in the log»; `tests/test_main.py::test_rejected_request_is_logged_without_client_or_key` |
| El cliente (nunca la clave) va en el log `request`, en `audit`, en `agent_run` y en los metadatos de la traza | `app/middleware.py`: `client_of` y `_finish`; `app/agent.py`: `RunState.trace_metadata`, `Agent.run` y `Agent._call_tool` | Escenario «A client with a valid key gets an answer and is named in the log»; `tests/test_agent.py::test_agent_names_the_client_in_audit_agent_run_and_traces` |
| Más de `RATE_LIMIT_PER_MINUTE` peticiones por cliente en un minuto responden `429 {"detail": "rate limit exceeded"}` con `Retry-After` | `app/ratelimit.py`: `RateLimiter.check` (ventana fija de 60 s sobre el reloj inyectado); `app/main.py:ClientGuard` arma el 429 | `tests/test_ratelimit.py`; escenarios «A client over the limit waits until the minute is over» y «Two clients do not share the limit»; contrato `test_too_many_requests_returns_429_with_retry_after` |
| `RATE_LIMIT_PER_MINUTE` y `ENVIRONMENT` inválidos impiden arrancar | `app/config.py`: `Settings._known_environment` y `Settings._must_be_positive` | `tests/test_config.py::test_invalid_environment_or_rate_limit_stops_startup` |
| La página pide la clave en un campo `password`, la guarda en `sessionStorage` y la manda en `X-API-Key`; nunca va en el almacenamiento permanente del navegador, en la URL ni en el HTML | `app/static/index.html`: campo `data-testid="api-key"`, `readStoredKey`, `storeKey` y el `fetch` de `sendQuestion` | `tests/test_main.py::test_home_page_has_a_password_key_field_kept_in_session_storage`; pruebas de `e2e/` (con `E2E_API_KEY`) |
| Con `401` la página muestra «Clave inválida»; con `429`, «Demasiadas preguntas; espera N segundos» (N de `Retry-After`) | `app/static/index.html`: `errorTextFor` | `tests/test_main.py::test_home_page_has_a_password_key_field_kept_in_session_storage`; pruebas de `e2e/` (clave equivocada) |

## Seguridad reforzada (`spec/05-security-hardening.md`, puntos 1 a 9)

Estas reglas se aplican en cada petición. Sus pruebas están en `tests/test_pii.py`,
`tests/test_guardrails.py`, `tests/test_security.py`, `tests/test_concurrency.py` y en
los escenarios de `tests/features/security.feature` (pasos en
`tests/test_security_steps.py`).

| Regla | Dónde está en el código | Cómo se comprueba |
| --- | --- | --- |
| La PII (`email`, `phone`, `card` con Luhn, `curp`, `rfc`) se cambia por `[REDACTED:<kind>]`; los datos del directorio nunca se ocultan | `app/pii.py`: `redact_pii` y `luhn_valid` (función pura, sin red ni log) | `tests/test_pii.py` (un positivo y un negativo por tipo; `EMP-0001`, nombres, departamentos y el JSON de un empleado intactos; idempotencia); escenario «Directory data is never redacted» |
| La pregunta y todo el `history` se limpian antes de enrutar; el modelo, el log, la auditoría y la traza solo ven el texto limpio; la petición no se rechaza | `app/main.py`: `_screen_input` y `_redact_history`, llamados en `ask` antes de `route_question` | Escenarios «A question with an email is answered with the email redacted» y «The email never reaches the log or the trace»; `tests/test_concurrency.py` (`security.pii` cuenta 20) |
| La respuesta final pasa por secretos, PII, vacía y recorte, en ese orden, dentro de la función trazada `agent_run` | `app/guardrails.py`: `validate_answer`; `app/agent.py`: `Agent._checked_loop` | `tests/test_guardrails.py`; `tests/test_security.py::test_empty_model_answer_is_replaced_by_the_safe_message` y `test_answer_is_trimmed_to_max_answer_chars` |
| Una clave de `API_KEYS` o `CF_API_TOKEN` nunca sale en la respuesta: se cambia por `[REDACTED:secret]`; un secreto vacío se ignora | `app/guardrails.py`: `redact_secrets`; `app/config.py`: `Settings.secret_values` (nunca en `repr`) | Escenario «An API key in the model answer is redacted»; `tests/test_guardrails.py::test_secret_in_answer_is_redacted_and_not_mistaken_for_a_phone`; `tests/test_security.py::test_secret_values_skip_empty_values_and_stay_out_of_repr` |
| `MAX_ANSWER_CHARS` vale 2000 por omisión y debe ser un entero mayor que 0 | `app/config.py`: `Settings.max_answer_chars`, `_production_values` y `_must_be_positive` | `tests/test_security.py::test_max_answer_chars_defaults_to_2000_and_rejects_invalid_values` |
| Mínimo privilegio en herramientas: `get_employee` acepta `EMP-####` o un nombre de 1 a 80 caracteres sin control ni PII; `search_by_department`, solo un departamento del directorio. Un argumento inválido no llega al directorio y el error no repite el valor | `app/guardrails.py`: `validate_tool_args`; `app/agent.py`: `Agent._call_tool` | `tests/test_guardrails.py::test_tool_arguments_follow_least_privilege`; `tests/test_security.py::test_invalid_tool_argument_never_reaches_the_directory`; escenario «An invalid tool argument never reaches the directory» |
| Los argumentos del evento `audit` se registran sin PII | `app/agent.py`: `audit_args` | `tests/test_agent.py::test_agent_logs_audit_and_agent_run_without_any_text`; `tests/test_security.py::test_invalid_tool_argument_never_reaches_the_directory` |
| La inyección de instrucciones se detecta sin acentos ni mayúsculas y solo se audita | `app/guardrails.py`: `detect_injection` e `INJECTION_PHRASES`; `app/main.py`: `_screen_input` | `tests/test_guardrails.py`; escenario «A prompt injection attempt is audited but not blocked» |
| Cada detección escribe `security` en el log y en la traza con `request_id`, `client`, `stage`, `control` y `kinds`, nunca el valor | `app/security.py`: `SecurityAudit.record` (su firma no recibe texto) | `tests/test_security.py::test_security_event_goes_to_log_metrics_and_trace_with_five_fields`; escenario «The email never reaches the log or the trace» |
| `GET /metrics` agrega `security` (conteo por control) sin cambiar las llaves anteriores | `app/metrics.py`: `Metrics.record_security` y `snapshot` | `tests/test_security.py::test_security_metrics_start_at_zero_and_keep_the_previous_keys` |
| `POST /ask` agrega `redactions` (tipos ocultados en la pregunta o en la respuesta, sin repetir) sin cambiar los campos anteriores | `app/main.py`: `ask` y `app/pii.py`: `merge_kinds` | `tests/test_security.py::test_ask_response_only_adds_an_empty_redactions_list`; escenarios con «the redactions contain» |
| 20 peticiones `/ask` simultáneas responden 200 con `request_id` distintos, `/metrics` las cuenta y el límite sigue contando por cliente | `app/metrics.py`, `app/logs.py` y `app/ratelimit.py` (cada uno con su `threading.Lock`) | `tests/test_concurrency.py::test_twenty_simultaneous_questions_are_all_answered_and_counted` |

Límite conocido: el estado del límite vive en memoria, por proceso (ADR 0011). Con varias
copias del servicio el límite real es `RATE_LIMIT_PER_MINUTE` por copia; el contenedor
arranca un solo proceso uvicorn.
