# Seguridad del HR Assistant

Controles del producto en producción, dónde están en el código y cómo se comprueba cada uno. Las reglas que
impiden arrancar en producción están en `doc/compliance-checklist.md`. Decisiones: ADR 0008 (adaptador del gateway,
con su nota de vigencia sobre `CF_AIG_TOKEN`), 0011 (claves), 0012 (límite), 0013 (compliance y despliegue con
compuerta), 0014 (PII y datos inventados), 0015 (caché), 0016 (workers) y 0017 (trazas).

Orden de las guardas de `POST /ask`: clave (401), límite (429), esquema (422), inyección (400), PII, caché,
agente, salida.

## Validación de entradas y salidas

| Control | Dónde está en el código | Cómo se comprueba |
| --- | --- | --- |
| Esquema: pregunta no vacía ni solo espacios, largo máximo `MAX_QUESTION_CHARS`, historial con rol `user` o `assistant` (422) | `app/main.py`: `build_request_models` | Escenarios de `tests/features/ask.feature` y pruebas de `tests/test_api.py`; e2e `test_sending_an_empty_question_shows_an_error_in_spanish` |
| Inyección de instrucciones en la pregunta o el historial, sin distinguir mayúsculas ni acentos: `400 input rejected` | `app/guardrails.py`: `INJECTION_PATTERN`, `is_injection`, `RequestGuard._reject_injection` | `tests/test_reto_guardrails.py::test_injection_is_detected_ignoring_case_and_accents`; escenarios «A prompt injection in the question is rejected» y «A prompt injection in the history is rejected» de `tests/features/reto.feature`; contrato `test_prompt_injection_is_rejected`; e2e `test_a_prompt_injection_question_shows_the_rejected_notice` |
| La clave se revisa antes que la inyección y que el esquema (401 antes que 400 y 422) | `app/main.py`: `require_client` como dependencia de la ruta | Escenario «The key is checked before the injection guard»; `tests/test_production_api.py::test_missing_key_is_reported_before_invalid_fields` |
| Salida nunca vacía («No encontré una respuesta.»), recortada a `MAX_ANSWER_CHARS`, y reemplazada por «No puedo mostrar esa respuesta.» si trae una clave de `API_KEYS`, `Bearer <token>` o 32 o más caracteres hexadecimales | `app/guardrails.py`: `validate_output`, `RequestGuard.check_output`, `SECRET_PATTERNS` | `tests/test_reto_guardrails.py::test_answers_are_never_empty_too_long_or_leaking_secrets` |
| `request_id` del cliente solo con `[A-Za-z0-9._:-]`, 1 a 128; si no, UUID (no inyecta líneas en el log) | `app/main.py`: `resolve_request_id` | Pruebas de observabilidad de la sesión 2 (`tests/test_api.py`, `tests/features/observability.feature`) |
| Errores inesperados como `500 internal error` y fallas del modelo como `502 model unavailable`, sin detalles internos | `app/main.py`: middleware `observe` y `model_unavailable` | Pruebas de `tests/test_api.py` y `tests/test_gateway.py` |
| La página pinta todo con `textContent`, nunca con `innerHTML` | `app/static/index.html` | Revisión de código; pruebas e2e de `e2e/test_chat_page.py` |

## Sin datos inventados

En producción el modelo real inventó un teléfono para un empleado: el directorio no tiene teléfonos. La defensa
tiene dos capas: el prompt evita que el modelo invente y el enmascarado de la respuesta es la red de seguridad si
aun así lo hace (spec/05-reto.md, puntos 5 y 6).

| Control | Dónde está en el código | Cómo se comprueba |
| --- | --- | --- |
| El prompt de sistema limita la respuesta a los datos de las herramientas (id, nombre, departamento, puesto, fecha de ingreso y estado), prohíbe inventar y, si piden otro dato de una persona (teléfono, correo, dirección, salario u otro), obliga a responder exactamente «No tengo ese dato en el directorio.» | `app/agent.py`: `SYSTEM_PROMPT` | `tests/test_reto_guardrails.py::test_system_prompt_forbids_personal_data_outside_the_directory` |
| El detector de teléfonos reconoce de 7 a 10 dígitos, con o sin `+52`, espacios, guiones, puntos o paréntesis; fechas `AAAA-MM-DD`, `EMP-0004`, NSS y tarjetas no cuentan como teléfono | `app/pii.py`: detector `phone` en `DETECTORS` | `tests/test_reto_guardrails.py::test_every_phone_format_from_seven_to_ten_digits_is_detected_and_masked` y `test_dates_ids_nss_and_cards_are_not_reported_as_phones` |
| Red de seguridad: si el modelo devuelve un teléfono, la respuesta sale con `[TELEFONO]`, `pii_detected: ["phone"]` y `audit pii_detected` con `where: answer`; el número no llega al log | `app/guardrails.py`: `RequestGuard.check_output`; `app/pii.py`: `mask` | `tests/test_reto_guardrails.py::test_a_phone_invented_by_the_model_is_masked_in_the_answer` |
| Prueba de humo en producción: pregunta «¿Cuál es el número de teléfono de EMP-0001?» y falla si la respuesta no es 200 o trae algo con forma de teléfono (7 o más dígitos, sin contar fechas) | `verification/production.py`: `PHONE_QUESTION`, `shows_a_phone` (fuera de `product/`) | `uv run python -m verification production <url>` después de publicar: línea `POST /ask teléfono` con `[OK]` |

## Secretos

| Control | Dónde está en el código | Cómo se comprueba |
| --- | --- | --- |
| Una clave por cliente en `API_KEYS`; en producción no vacía y de 16 caracteres o más | `app/auth.py`: `parse_api_keys`; `app/compliance.py`: `_key_violations` | `tests/test_security.py::test_compliance_reports_every_broken_rule_only_in_production`; reglas 2 y 7 de `doc/compliance-checklist.md` |
| Comparación en tiempo constante (`hmac.compare_digest`, recorriendo todas las claves) | `app/auth.py`: `ApiKeyAuthenticator.authenticate` | `tests/test_security.py::test_authenticator_returns_the_client_only_for_a_matching_key` |
| Las claves no salen en `repr`, log, trazas, errores ni la página; un `API_KEYS` mal formado solo dice posición y largo | `app/auth.py` (`ApiKey.__repr__`, `_entry_error`); `app/config.py` (`repr=False`) | Contrato `test_a_broken_api_keys_never_leaks_the_key`; `tests/test_security.py::test_settings_validate_environment_and_rate_limit_and_hide_the_keys` |
| `/docs` y `/openapi.json` son públicos y nunca contienen una clave | `app/main.py`: `create_app`, `APIKeyHeader` sin valores | Contratos `test_swagger_page_needs_no_key` y `test_no_public_document_leaks_the_key`; `tests/test_reto_api.py::test_openapi_documents_version_tags_errors_and_the_key_scheme` |
| `CF_API_TOKEN` y `CF_AIG_TOKEN` guardados con `repr=False` y nunca escritos en log, traza ni mensaje de error; `LANGSMITH_API_KEY` solo la lee el SDK del entorno, la configuración solo sabe si existe | `app/config.py`: `_cloudflare` (campo `cf_aig_token`), `_has_langsmith_key`; `app/tracing.py` | `tests/test_cost_config.py::test_gateway_auth_token_is_read_but_hidden_from_the_settings_repr` y `test_config_error_does_not_reveal_the_gateway_auth_token`; `tests/test_gateway.py::test_gateway_failure_does_not_leak_the_gateway_token`; pruebas de `tests/test_config.py` y `tests/test_tracing.py` |
| `CF_AIG_TOKEN` (gateway con "Authenticated Gateway" encendido) es opcional: con valor se manda como `cf-aig-authorization: Bearer <token>`, además de `Authorization` con `CF_API_TOKEN`; vacío, el encabezado no se manda | `app/gateway.py`: `GATEWAY_AUTH_HEADER`; `app/config.py`: `cf_aig_token` | `tests/test_gateway.py::test_gateway_token_is_sent_as_cf_aig_authorization` y `test_without_gateway_token_the_cf_aig_authorization_header_is_not_sent`; `tests/test_cost_config.py::test_gateway_auth_token_is_optional_and_empty_by_default` |
| Secretos fuera del repositorio: `.env` no se versiona; en Render `API_KEYS`, `CF_ACCOUNT_ID`, `CF_API_TOKEN`, `CF_AIG_TOKEN` y `LANGSMITH_API_KEY` con `sync: false` | `.env.example` (sin valores); `render.yaml` | Revisión de `render.yaml` antes de aprobar la publicación; en la fábrica nadie puede leer `.env` (`hooks/permissions.py`) |
| La página guarda la clave solo en `sessionStorage` (campo `type="password"`) | `app/static/index.html` | `tests/test_production_api.py::test_page_has_a_password_key_field_kept_only_in_session_storage`; e2e `test_a_wrong_api_key_shows_invalid_key_message` |

Lección operativa: los valores se pegan en Render > Environment sin comillas. Un valor pegado con comillas rompió
la URL del gateway; Cloudflare respondió 401 «Account ID missing from request path» y el log solo mostraba
`error_type: ModelUnavailable`, sin el código de estado. Diagnóstico en `doc/observability.md`.

## Auditoría

| Control | Dónde está en el código | Cómo se comprueba |
| --- | --- | --- |
| Evento `audit` con `action` `tool_call`, `auth_failed`, `rate_limited`, `input_rejected`, `pii_detected` (`types`, `where`) y `output_blocked`, siempre con `request_id` y `client` (o `null`) | `app/telemetry.py`: `RequestLog.audit`, `RequestLog.security_audit`; llamadas en `app/main.py` (`require_client`) y `app/guardrails.py` | `tests/test_reto_guardrails.py::test_security_audit_events_never_carry_the_value_question_or_key` |
| Un `audit` de seguridad solo acepta los campos `types` y `where`: el valor detectado, la pregunta y la clave no pueden llegar | `app/telemetry.py`: `SECURITY_AUDIT_FIELDS` (lanza `ValueError` con otro campo) | La misma prueba; revisión de código |
| Cada guarda suma su contador en `security` de `/metrics` | `app/metrics.py`: `add_security_event` | `tests/test_reto_observability.py::test_metrics_count_each_security_event`; contrato `test_metrics_report_cost_per_request_errors_and_security` |
| Log sin texto de preguntas ni respuestas; errores solo con `error_type` | `app/telemetry.py` | Pruebas de telemetría de la sesión 2 (`tests/test_telemetry.py`) |
| Log y métricas con candado: con varios hilos no se mezclan líneas ni se pierden conteos | `app/telemetry.py` y `app/metrics.py`: `threading.Lock` | `tests/test_reto_observability.py::test_metrics_stay_exact_under_concurrent_requests` |

## Datos sensibles (PII)

| Control | Dónde está en el código | Cómo se comprueba |
| --- | --- | --- |
| Detección de `email`, `phone` (7 a 10 dígitos), `curp`, `rfc`, `card` (Luhn) y `nss` con regex compiladas una vez; sin dobles conteos; `EMP-0004` y fechas no son PII | `app/pii.py`: `detect`, `passes_luhn`, `DETECTORS` | `tests/test_reto_guardrails.py::test_each_kind_of_personal_data_is_detected` y `test_ids_dates_and_overlapping_data_are_not_misreported`; contrato `test_questions_without_personal_data_do_not_report_it` |
| `PII_POLICY=mask`: `[EMAIL]`, `[TELEFONO]`, `[CURP]`, `[RFC]`, `[TARJETA]`, `[NSS]` antes del enrutador, la caché, el modelo, el log y la traza; la respuesta también se enmascara; `pii_detected` con los tipos | `app/pii.py`: `mask`; `app/guardrails.py`: `RequestGuard.check_input`, `check_output`; `app/main.py`: `_with_pii` | `test_masking_replaces_each_value_with_its_label`; `test_personal_data_is_masked_before_the_model_and_in_the_answer`; escenario «Personal data is masked and reported by type»; contrato `test_personal_data_is_detected_and_reported_by_type`; e2e `test_a_question_with_an_email_shows_the_sensitive_data_notice` |
| `PII_POLICY=block`: `400 sensitive data not allowed` | `app/guardrails.py`: `RequestGuard.check_input` | Escenario «The block policy rejects personal data»; contrato `test_block_policy_rejects_personal_data` |
| Nunca se guarda en caché una respuesta con PII en la entrada o la salida, ni una salida bloqueada | `app/main.py`: `_remember`; `app/cache.py`: `is_storable` (defensa en profundidad) | `tests/test_reto_costs.py::test_personal_data_and_blocked_outputs_are_never_cached` |
| Trazas sin texto en producción: `HIDE_INPUTS=true` y `HIDE_OUTPUTS=true` | `app/tracing.py`: `LangSmithTracer`; `app/compliance.py`: `_tracing_violations` | Regla 3 de `doc/compliance-checklist.md`; `tests/test_reto_observability.py::test_langsmith_traces_carry_metadata_and_tags` |

Límite conocido: las regex no cubren formatos raros (por ejemplo, un teléfono escrito con palabras o con más de 10
dígitos sin `+52`). Se aceptan falsos negativos raros a cambio de no rechazar preguntas legítimas (ADR 0014). Los
datos del directorio (nombre, puesto, departamento, fecha de ingreso) no son PII para el detector y sí llegan al
modelo como resultado de las herramientas.

## Mínimo privilegio

| Control | Dónde está en el código | Cómo se comprueba |
| --- | --- | --- |
| `POST /ask` y `GET /metrics` exigen clave; solo `/`, `/health`, `/docs` y `/openapi.json` son públicos | `app/main.py`: `require_client` | Regla 5 de `doc/compliance-checklist.md`; contrato `test_asking_without_a_key_returns_401` |
| Límite por cliente (`RATE_LIMIT_PER_MINUTE=60` en Render, por proceso: hasta `WEB_CONCURRENCY` veces ese valor en total) | `app/ratelimit.py`: `RateLimiter.check` | Regla 8 de `doc/compliance-checklist.md`; `tests/test_security.py::test_concurrent_requests_never_exceed_the_limit` |
| El agente solo tiene dos herramientas de solo lectura (`get_employee`, `search_by_department`) sobre un archivo local, y un bucle con tope `AGENT_MAX_STEPS` | `app/agent.py`: `TOOL_ARGUMENTS`; `app/directory.py` | `tests/test_agent.py` y `tests/test_directory.py` |
| Contenedor `python:3.12-slim` con usuario sin privilegios (`appuser`, uid 10001); solo copia `app/` y `data/` | `Dockerfile` | Etapa `docker` del CI (construye la imagen); revisión de código |
| CI con `permissions: contents: read`; Render publica solo si el CI pasa (`autoDeployTrigger: checksPass`) | `.github/workflows/ci.yml`; `render.yaml` | Revisión de código antes de aprobar la publicación (ADR 0013); `verification production <url>` después de publicar |
| En producción no arranca con el modelo `fake` ni con trazas que muestren texto | `app/compliance.py` | Reglas 1 y 3 de `doc/compliance-checklist.md` |
| Token de Workers AI (`CF_API_TOKEN`) con el mínimo: un token propio del servicio, limitado a la cuenta de `CF_ACCOUNT_ID`, solo con el permiso de cuenta de Workers AI necesario para inferencia; sin permisos de zona, DNS, Workers ni de edición del gateway; con fecha de vencimiento y rotación | Fuera del código: panel de Cloudflare > API Tokens; el producto solo lo usa en `app/gateway.py` (encabezado `Authorization`) | Revisión manual del token en Cloudflare al crearlo o rotarlo; si falta un permiso, `/ask` responde 502 y `verification production` lo detecta |
| Token del gateway (`CF_AIG_TOKEN`) con el mínimo: un token separado del de Workers AI, limitado a la misma cuenta y solo con el permiso `AI Gateway: Run` (ejecutar el gateway, no editarlo ni leer sus logs); con fecha de vencimiento y rotación. Separarlo permite revocar uno sin tocar el otro | Fuera del código: panel de Cloudflare > API Tokens; el producto solo lo usa en `app/gateway.py` (encabezado `cf-aig-authorization`) | Revisión manual del token en Cloudflare al crearlo o rotarlo; con el gateway autenticado y el token ausente o inválido, `/ask` responde 502 y `verification production` lo detecta |
| Clave de LangSmith (`LANGSMITH_API_KEY`) con el mínimo: una clave de servicio (no la personal de una persona), en un espacio de trabajo dedicado al producto, usada solo para escribir trazas en el proyecto `hr-assistant-reto`; con rotación. Con `HIDE_INPUTS`/`HIDE_OUTPUTS` las trazas no guardan texto de conversaciones | Fuera del código: LangSmith > Settings > API Keys; el producto solo la pasa al SDK desde el entorno | Revisión manual en LangSmith al crearla o rotarla; las trazas de una petición de `verification production` aparecen en el proyecto |
| En la fábrica, cada agente escribe solo en sus carpetas, nadie lee `.env` y nadie publica sin `output/approved.txt` | `hooks/permissions.py` (fuera de `product/`) | `tests/test_permissions.py` de la fábrica |

## Qué hacer ante un incidente

- Clave de cliente filtrada: quitarla de `API_KEYS` en Render (el servicio se reinicia) y entregar una nueva.
- `CF_API_TOKEN` o `LANGSMITH_API_KEY` filtrados: revocar en Cloudflare o LangSmith, crear uno nuevo con los
  mismos permisos mínimos y actualizarlo en Render > Environment.
- `CF_AIG_TOKEN` filtrado: revocarlo en Cloudflare (API Tokens), crear uno nuevo solo con `AI Gateway: Run` y
  reemplazarlo en Render > Environment (sin comillas); el servicio se reinicia con el valor nuevo. `CF_API_TOKEN`
  no cambia. Comprobar con `verification production <url>`.
- `/ask` responde 502 justo después de cambiar un secreto: revisar en Render que el valor no tenga comillas ni
  espacios (ver la lección operativa de "Secretos" y `doc/observability.md`).
- Para investigar: buscar el `request_id` en el log de Render y en LangSmith (`doc/observability.md`); los eventos
  `audit` dicen qué guarda actuó sin revelar el dato.
