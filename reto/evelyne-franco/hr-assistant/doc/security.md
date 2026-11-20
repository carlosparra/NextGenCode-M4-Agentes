# Seguridad del HR Assistant

Este documento reúne **todos los controles de seguridad** que existen hoy en el código: los de las sesiones 1 a 4
(acceso, límite, compliance, logs sin contenido, despliegue), los del reto de seguridad reforzada
(`spec/05-security-hardening.md`: PII, validación de salidas y de argumentos, inyección, auditoría y concurrencia),
los del sistema multi-agente (`spec/06-multiagente.md`: mínimo privilegio entre especialistas, comprobación contra
los datos y traza raíz sin texto) y los de su Adenda 1 (vacaciones por empleado: normalización de ids, herramienta
`vacation_days` y comprobación de sus números).

Cada fila dice dónde está el control y con qué prueba se comprueba. Las pruebas corren con
`uv run python -m verification unit` (unitarias y Gherkin, cobertura de 80 % o más) y `contract`; las de navegador con
`verification e2e`; la versión publicada con `uv run python -m verification production <url>`. El detalle regla por
regla de producción está en `doc/compliance-checklist.md`; las decisiones, en los ADR 0010 a 0015 (la Adenda 1 está
en el ADR 0014).

## Modelo de amenazas, en breve

| Activo | Amenaza | Controles principales |
| --- | --- | --- |
| Directorio de empleados | Acceso sin permiso, abuso por volumen | Clave por cliente, límite por minuto, herramientas de solo lectura |
| Claves (`API_KEYS`, `CF_API_TOKEN`, `LANGSMITH_API_KEY`) | Fuga en log, traza, error o respuesta | `SecretStr`, errores sin valores, `[REDACTED:secret]` en la salida |
| PII ajena al directorio (correo, teléfono, tarjeta, CURP, RFC) | Que viaje al supervisor, al modelo, al log o a la traza | `guard` con `redact_pii` en la entrada, argumentos auditados sin PII, `reviewer` en la salida |
| Comportamiento de los agentes | Inyección de instrucciones, argumentos abusivos, uso de herramientas ajenas | Bucle acotado por especialista, registro propio de herramientas, argumentos validados, auditoría de frases conocidas |
| Exactitud de la respuesta | Ids de empleado, números de política o días de vacaciones inventados por el modelo | Antigüedad y días calculados en código (`vacation_days`); `reviewer`: comprobación contra el directorio, las políticas y los resultados de `vacation_days` |
| Servicio publicado | Configuración insegura, código sin probar | Compliance al arrancar, CI encadenado, publicación solo si el pipeline pasa |

## Controles

### Acceso y abuso (sesión 4)

| Control | Dónde está en el código | Cómo se comprueba |
| --- | --- | --- |
| `POST /ask` y `GET /metrics` exigen `X-API-Key`; sin clave válida responden `401 {"detail": "invalid or missing API key"}` sin gastar cupo | `app/main.py`: `ClientGuard.__call__`, dependencia de `ask` y `metrics_snapshot` | Escenario «A request without a valid key is rejected» (`production.feature`); `tests/test_main.py`; contratos de 401 |
| `GET /`, `GET /health` y `/docs` quedan abiertos y no exponen datos | `app/main.py`: `_add_open_routes` | Escenario «The page, the health check and the docs need no key» |
| Comparación de claves en tiempo constante contra todas las configuradas | `app/auth.py`: `ApiKeyAuth.client_for` (`hmac.compare_digest`, sin cortar al encontrar) | `tests/test_auth.py::test_each_key_maps_to_its_client_and_unknown_keys_to_none` |
| `API_KEYS` mal formada o con claves repetidas impide arrancar; el error dice posición y largo, nunca el valor | `app/auth.py`: `parse_api_keys`, `_parse_entry`, `_malformed`; `app/config.py`: `_production_values` (fuera de Pydantic) | `tests/test_auth.py::test_malformed_entry_error_names_its_position_and_length_but_never_its_value`; `tests/test_config.py::test_api_keys_never_appear_in_settings_or_startup_errors` |
| El nombre del cliente solo admite `[A-Za-z0-9._-]{1,64}` (evita inyección en logs) | `app/auth.py`: `VALID_CLIENT` | `tests/test_auth.py::test_malformed_api_keys_are_rejected` |
| Límite de `RATE_LIMIT_PER_MINUTE` peticiones por cliente; al pasarse, `429` con `Retry-After`; una petición negada no gasta cupo | `app/ratelimit.py`: `RateLimiter.check` (ventana fija de 60 s, `threading.Lock`); `app/main.py`: `ClientGuard` | `tests/test_ratelimit.py`; escenarios «A client over the limit waits until the minute is over» y «Two clients do not share the limit» |
| La página guarda la clave en `sessionStorage`, en un campo `password`, y pinta todo con `textContent` (sin HTML inyectable) | `app/static/index.html`: `readStoredKey`, `storeKey`, `sendQuestion`, `errorTextFor` | `tests/test_main.py::test_home_page_has_a_password_key_field_kept_in_session_storage`; pruebas de `e2e/` |

### Configuración y despliegue (sesión 4)

| Control | Dónde está en el código | Cómo se comprueba |
| --- | --- | --- |
| Con `ENVIRONMENT=production` no arranca con `MODEL_PROVIDER=fake`, sin `API_KEYS`, con claves de menos de 16 caracteres o con trazas que muestran entradas o salidas | `app/compliance.py`: `production_violations` y `enforce`, primera línea de `create_app` | Escenario «Production refuses to start with unsafe settings»; `tests/test_compliance.py` |
| Valores de configuración inválidos (`ENVIRONMENT`, proveedor, números, `MAX_ANSWER_CHARS`) impiden arrancar | `app/config.py`: validadores de `Settings` | `tests/test_config.py::test_invalid_environment_or_rate_limit_stops_startup`; `tests/test_security.py::test_max_answer_chars_defaults_to_2000_and_rejects_invalid_values` |
| `CF_API_TOKEN` es `SecretStr`; `LANGSMITH_API_KEY` nunca se guarda (solo se revisa que exista) | `app/config.py`: `Settings.cf_api_token`, `load_settings`; `app/tracing.py`: `Tracer.enabled` | `tests/test_config.py::test_booleans_are_parsed_and_api_key_is_never_stored` y `test_gateway_provider_requires_every_cloudflare_variable_and_hides_the_token` |
| Una falla del gateway (en el supervisor o en el especialista) se vuelve `502 model unavailable` sin el token ni el mensaje original | `app/gateway.py`; `app/main.py`: `_add_model_error_handler` (registra solo el tipo) | `tests/test_gateway.py::test_every_gateway_failure_becomes_model_unavailable_without_the_token` |
| Trazas apagadas por omisión; encendidas, ocultan entradas y salidas por omisión | `app/tracing.py`: `TracingOptions`, `Tracer` (fija `LANGSMITH_HIDE_INPUTS/OUTPUTS`) | `tests/test_tracing.py::test_tracing_does_nothing_without_api_key` y `test_tracing_wraps_with_langsmith_and_hides_inputs` |
| La imagen corre sin root, sin `.env`, pruebas ni documentos | `Dockerfile` (`USER hr`, uid 10001); `.dockerignore` | Trabajo `docker` de `.github/workflows/ci.yml` |
| Render publica solo si `style`, `unit`, `e2e` y `docker` pasan; los secretos van con `sync: false`; CI con `permissions: contents: read` | `render.yaml` (`autoDeployTrigger: checksPass`); `.github/workflows/ci.yml` (`needs`) | El pipeline mismo; `scripts/smoke.py` y `verification production <url>` tras publicar |

### Trazabilidad sin contenido (sesiones 2 a 4)

| Control | Dónde está en el código | Cómo se comprueba |
| --- | --- | --- |
| El log nunca lleva el texto de la pregunta ni de la respuesta, ni la clave: solo conteos, modelo, ruta, costo, cliente, especialista y motivo del supervisor | `app/agent.py`: `Agent.run` (`agent_run`); `app/middleware.py`: `_finish` (nunca lee `X-API-Key`) | Escenario «The log never contains the question or the answer»; `tests/test_agent.py::test_agent_logs_audit_and_agent_run_without_any_text`; escenarios con «the key that was sent appears nowhere in the log» |
| `X-Request-ID` del cliente solo se acepta si cumple `[A-Za-z0-9._-]{1,128}`; si no, se genera un UUID | `app/middleware.py`: `resolve_request_id` | Escenario «An invalid client request id is replaced by a UUID» |
| Los errores internos responden `500` con `request_id` y registran solo el tipo de la excepción | `app/middleware.py`: `ObservabilityMiddleware.__call__` | Escenario «An internal error returns 500 with the request id and logs only the type» |
| Cada línea de log es un JSON de una sola línea aunque traiga saltos o caracteres no ASCII | `app/logs.py`: `JsonLogger.emit` | `tests/test_logs.py::test_non_ascii_and_newlines_stay_on_one_line` |
| Pregunta vacía o de más de `MAX_QUESTION_CHARS` responde `422` antes de que corra ningún agente | `app/main.py`: `_validate_question` | Escenario «A validation error still carries the request id and is logged»; `tests/test_main.py` |
| Cada especialista tiene tope de pasos (`AGENT_MAX_STEPS`) y solo herramientas de solo lectura | `app/agent.py`: `Agent._loop`, `Agent._call_tool`; ADR 0003 | `tests/test_agent.py::test_agent_reports_max_steps_when_it_stops_at_the_cap` |

### Seguridad reforzada (reto, `spec/05-security-hardening.md`)

| Control | Dónde está en el código | Cómo se comprueba |
| --- | --- | --- |
| Detección de PII (`email`, `phone`, `card` con Luhn, `curp`, `rfc`) que cambia cada coincidencia por `[REDACTED:<kind>]`; función pura, sin red ni log | `app/pii.py`: `redact_pii`, `luhn_valid`, `merge_kinds` | `tests/test_pii.py` (positivo y negativo por tipo, idempotencia) |
| Los datos del directorio (`EMP-0001`, nombres, departamentos, fechas, estado) nunca se ocultan | `app/pii.py`: patrones con largo exacto y límites de dígito | `tests/test_pii.py::test_directory_data_is_never_redacted`; escenario «Directory data is never redacted» |
| La pregunta y todo el `history` se limpian en el agente `guard`, **antes** del supervisor y del enrutador; desde ahí el supervisor, el modelo, el log, la auditoría y la traza solo ven el texto limpio; la petición no se rechaza | `app/guard.py`: `screen_input`, `redact_history`; `app/orchestrator.py`: `RequestPipeline._guard` (reemplaza el texto en `RequestContext`) | Escenarios «A question with an email is answered with the email redacted» y «The email never reaches the log or the trace» |
| Los argumentos del evento `audit` se registran sin PII y recortados a 64 caracteres | `app/agent.py`: `audit_args` | `tests/test_agent.py::test_agent_logs_audit_and_agent_run_without_any_text` |
| Validación de argumentos: `get_employee` acepta `EMP-####` o un nombre de 1 a 80 caracteres sin caracteres de control ni PII; `search_by_department`, solo un departamento del directorio; `search_policy`, un tema de 1 a 60 caracteres sin caracteres de control; `vacation_days`, solo un `EMP-####` exacto (Adenda 1). Un argumento inválido no llega a los datos, registra `security` con `stage=output` y `control=tool_args`, y el error no repite el valor | `app/guardrails.py`: `validate_tool_args`, `_employee_reason`, `_department_reason`, `_topic_reason`, `_vacation_reason`; `app/agent.py`: `Agent._call_tool` | `tests/test_guardrails.py::test_tool_arguments_follow_least_privilege`; `tests/test_security.py::test_invalid_tool_argument_never_reaches_the_directory`; `tests/test_policies.py::test_an_invalid_policy_topic_never_reaches_the_tool`; `tests/test_vacations.py::test_an_invalid_employee_id_is_rejected_before_the_tool_runs`; escenario «An invalid tool argument never reaches the directory» |
| **El evento `audit` y la validación no van en el mismo orden para todas las herramientas.** En `get_employee`, `search_by_department`, `search_policy` y en una herramienta ajena (`unknown_tool`), `Agent._call_tool` escribe el `audit` `tool_call` **antes** de saber si el argumento es válido: queda `audit` (con argumentos sin PII y recortados) aunque la herramienta no se ejecute. Solo `vacation_days` revisa el formato del id antes del `audit`: con formato inválido no deja `audit`, solo `security` `tool_args`, y el modelo recibe `{"error": "empleado no encontrado"}` en lugar de «argumento inválido para ...». Un `EMP-####` con formato válido que no existe sí se ejecuta, deja `audit`, no registra `security` y devuelve el mismo error | `app/agent.py`: `Agent._call_tool` (`vacation_rejected`) | `tests/test_security.py::test_invalid_tool_argument_never_reaches_the_directory` (dos argumentos inválidos dejan dos `audit`); `tests/test_vacations.py::test_an_invalid_employee_id_is_rejected_before_the_tool_runs` (ningún `audit` de `vacation_days`); `tests/test_vacations.py::test_an_unknown_employee_is_reported` |
| El nombre de herramienta que manda el modelo solo se repite en log y traza si es del especialista; si no, se registra `unknown_tool` | `app/agent.py`: `safe_tool_name` | `tests/test_security.py::test_unknown_tool_name_never_reaches_the_log` |
| Validación de la salida en el agente `reviewer`, en este orden: secretos, PII, vacía, comprobación contra los datos (ver abajo) y recorte a `MAX_ANSWER_CHARS` | `app/reviewer.py`: `Reviewer.review`; `app/guardrails.py`: `screen_answer`, `truncate_answer` | `tests/test_guardrails.py`; `tests/test_security.py::test_empty_model_answer_is_replaced_by_the_safe_message` y `test_answer_is_trimmed_to_max_answer_chars` |
| Una clave de `API_KEYS` o `CF_API_TOKEN` nunca sale en la respuesta: se cambia por `[REDACTED:secret]`; los secretos vacíos se ignoran y el más largo se reemplaza primero | `app/guardrails.py`: `redact_secrets`; `app/config.py`: `Settings.secret_values` | Escenario «An API key in the model answer is redacted»; `tests/test_guardrails.py::test_secret_in_answer_is_redacted_and_not_mistaken_for_a_phone` y `test_long_answer_is_trimmed_without_leaving_part_of_a_secret`; `tests/test_security.py::test_secret_values_skip_empty_values_and_stay_out_of_repr` |
| Respuesta vacía se cambia por «No pude generar una respuesta segura.» | `app/guardrails.py`: `SAFE_FALLBACK_ANSWER` | `tests/test_guardrails.py::test_empty_answer_becomes_the_fixed_safe_message` |
| Detección de inyección de instrucciones con frases conocidas, sin acentos, mayúsculas ni espacios repetidos, en la pregunta y en el historial; solo se audita | `app/guardrails.py`: `detect_injection`, `INJECTION_PHRASES`; `app/guard.py`: `screen_input` | `tests/test_guardrails.py::test_injection_phrases_are_detected_regardless_of_accents_and_case` y `test_normal_questions_are_not_flagged_as_injection`; escenario «A prompt injection attempt is audited but not blocked» |
| Cada detección escribe un evento `security` (`request_id`, `client`, `stage`, `control`, `kinds`) en el log, suma en métricas y abre un span `security` en la traza; la firma no recibe texto, así que nunca escribe el valor | `app/security.py`: `SecurityAudit.record` | `tests/test_security.py::test_security_event_goes_to_log_metrics_and_trace_with_five_fields`; escenario «The email never reaches the log or the trace» |
| `GET /metrics` agrega `security` (conteo por control) sin cambiar las llaves anteriores | `app/metrics.py`: `Metrics.record_security`, `snapshot` | `tests/test_security.py::test_security_metrics_start_at_zero_and_keep_the_previous_keys` |
| `POST /ask` agrega `redactions` (tipos ocultados en la pregunta o en la respuesta, sin repetir) sin cambiar los demás campos | `app/main.py`: `ask`; `app/pii.py`: `merge_kinds` | `tests/test_security.py::test_ask_response_only_adds_an_empty_redactions_list`; escenarios con «the redactions contain» |
| 20 peticiones `/ask` simultáneas, mezclando los dos especialistas: todas `200`, `request_id` distintos, `/metrics` cuenta 20 y el límite sigue contando por cliente | `app/orchestrator.py` (`RequestContext` por petición); `app/metrics.py`, `app/logs.py` y `app/ratelimit.py` (cada uno con su `threading.Lock`) | `tests/test_concurrency.py::test_twenty_simultaneous_questions_are_all_answered_and_counted` |

### Multi-agente (`spec/06-multiagente.md`)

| Control | Dónde está en el código | Cómo se comprueba |
| --- | --- | --- |
| **Mínimo privilegio entre especialistas:** `directory` solo tiene `get_employee` y `search_by_department`; `policy` solo `search_policy` y `vacation_days` (Adenda 1). Una herramienta ajena se trata como `unknown_tool`: no se ejecuta, registra `security` con `control=tool_args` y el modelo recibe un error | `app/agent.py`: `directory_tools`, `policy_tools`, `Agent._call_tool` (`safe_tool_name(name, self._tools)`); `app/orchestrator.py`: `RequestPipeline.__init__` | `tests/test_specialists.py::test_the_policy_specialist_cannot_read_the_directory` y `test_the_directory_specialist_cannot_read_the_policies`; `tests/test_vacations.py::test_the_directory_specialist_cannot_compute_vacation_days` |
| `search_policy` es de solo lectura sobre `data/policies.json`, cargado una vez al arrancar; un tema inexistente devuelve la lista de temas, no un error interno | `app/policies.py`: `PolicyBook.from_file`, `search_policy` | `tests/test_policies.py::test_search_policy_finds_a_topic_by_its_name`, `test_search_policy_finds_a_topic_by_keyword_without_accents_or_case` y `test_an_unknown_policy_topic_lists_the_available_topics` |
| Con `rule:policy` la política se consulta en código antes de llamar al modelo, con su evento `audit` `tool_call` y su lugar en `tools_used`: el modelo no decide si la consulta | `app/orchestrator.py`: `RequestPipeline._specialist`, `_prefetch`; `app/agent.py`: `Agent._start_messages`, `Agent._tool_message` | Escenario «A vacation question is answered by the policy specialist» (`multiagent.feature`) |
| El supervisor solo ve el texto que ya limpió `guard`, y su llamada a `MODEL_SMALL` va sin historial | `app/orchestrator.py`: `RequestPipeline._decide` (lee `ctx.question` después de `_guard`); `app/supervisor.py`: `Supervisor.decide` | `tests/test_supervisor.py::test_without_a_rule_the_small_model_is_called_once_without_history`. No hay prueba dedicada de que el supervisor reciba la pregunta sin PII; lo garantiza el orden de `RequestPipeline._request` |
| Una respuesta inválida del supervisor no se ejecuta como instrucción: cae a `directory` con `model_invalid` | `app/supervisor.py`: `parse_specialist` | `tests/test_supervisor.py::test_an_invalid_supervisor_answer_falls_back_to_directory` |
| **Comprobación contra el directorio:** una respuesta de `directory` que cita un `EMP-dddd` que no existe y que la persona no escribió se reemplaza por «No pude verificar la respuesta con el directorio. Intenta de nuevo.». Un id que la persona escribió de otra forma («empleado 77») cuenta como escrito por ella, porque `guard` ya lo normalizó | `app/reviewer.py`: `ungrounded_ids`, `Reviewer._ground` | `tests/test_reviewer.py::test_an_invented_employee_id_is_replaced`, `test_an_unknown_id_written_by_the_person_is_kept` y `test_an_unknown_id_written_another_way_counts_as_written_by_the_person` |
| **Comprobación contra las políticas:** cada número completo (`\d+`) de una respuesta de `policy` debe estar en el texto de alguna política consultada en la petición o, desde la Adenda 1, en algún resultado de `vacation_days` (ver abajo); si no, la respuesta se cambia por la frase armada con `vacation_days`, si lo hubo; si no, por la primera política consultada; si no hubo ninguna, por «No pude verificar la respuesta con las políticas. Intenta de nuevo.» | `app/reviewer.py`: `allowed_numbers`, `ungrounded_numbers`, `Reviewer._ground`; `app/agent.py`: `RunState.policy_texts` y `RunState.vacation_results` (se llenan en `Agent._remember`) | `tests/test_reviewer.py::test_policy_numbers_are_compared_as_whole_numbers`, `test_a_policy_answer_without_a_consulted_policy_gets_the_fixed_message` y `test_a_directory_answer_is_not_compared_against_policies`; escenario «A policy number that is not in the policy is replaced by the policy text» |
| Cada reemplazo registra `security` con `stage=output`, `control=ungrounded` y `kinds` `["employee_id"]` o `["policy_number"]`, nunca el valor | `app/reviewer.py`: `CONTROL_UNGROUNDED`, `KIND_EMPLOYEE_ID`, `KIND_POLICY_NUMBER`; `Reviewer.review` | Escenario «A policy number that is not in the policy is replaced by the policy text» («there is an output security event "ungrounded"») |
| **Traza raíz sin texto:** el run `request` y los runs `agent.guard`, `agent.supervisor` y `agent.reviewer` trazan funciones sin parámetros y devuelven solo resúmenes (tipos, conteos, decisiones), sin depender de `HIDE_INPUTS` ni `HIDE_OUTPUTS` | `app/orchestrator.py`: `RequestPipeline.run`, `_stage`; `GuardResult.summary`, `Decision.summary`, `Review.summary` | `tests/test_root_trace.py::test_code_agents_take_no_text_and_return_only_a_summary` |
| Todos los runs de la traza llevan `request_id` y `client`, nunca la clave; los spans `security` quedan dentro del agente que los registra | `app/orchestrator.py`: `RequestContext.metadata`; `app/tracing.py`: `Tracer.annotate` | `tests/test_root_trace.py::test_every_run_carries_request_id_and_client_and_never_the_key` y `test_security_spans_stay_inside_the_guard_and_the_reviewer` |
| Con las trazas apagadas, `annotate` no importa `langsmith` | `app/tracing.py`: `Tracer.annotate` | `tests/test_tracing.py::test_annotate_does_not_import_langsmith_when_tracing_is_off` |

### Adenda 1: vacaciones por empleado (`spec/06-multiagente.md`)

| Control | Dónde está en el código | Cómo se comprueba |
| --- | --- | --- |
| **Normalización de ids en `guard`**, sobre la pregunta ya limpia de PII: «empleado 4», «empleado #4», «emp 4», «emp-4» y «EMP4» (1 a 4 dígitos, sin importar mayúsculas) pasan a `EMP-0004`. Exige la palabra «empleado» o «emp» con límite de palabra y no acepta un quinto dígito pegado; un número suelto («2021», «año 2021») no es un id. El historial no se normaliza. El resumen de la traza solo lleva `ids_normalized` (un conteo) | `app/employee_ids.py`: `WRITTEN_ID_PATTERN`, `normalize_with_count`; `app/guard.py`: `screen_input`, `GuardResult.summary` | `tests/test_employee_ids.py::test_every_written_form_becomes_the_canonical_id`, `test_leading_zeros_give_the_same_id`, `test_a_canonical_id_is_left_unchanged`, `test_numbers_without_the_employee_word_are_not_ids` y `test_guard_normalizes_the_clean_question_and_reports_only_a_count` |
| **Regla `rule:policy_employee`**, antes de `rule:employee`: id `EMP-dddd` y tema `vacaciones` (palabra clave más larga de `match_question`) van a `policy` con el primer id; sin modelo. Con «prima vacacional» la regla no aplica y la pregunta sigue en `directory` | `app/supervisor.py`: `route_by_rules`, `VACATION_TOPIC`, `Decision.employee_id`; `app/metrics.py`: motivo `rule:policy_employee` | `tests/test_supervisor.py::test_an_employee_id_with_vacations_routes_to_policy_without_the_model` y `test_an_employee_id_with_the_vacation_bonus_stays_with_the_directory`; escenario «A question about an employee written another way still goes to the directory» |
| **`vacation_days` de solo lectura y con reloj inyectado:** lee el directorio con `Directory.find` (devuelve una copia), toma «hoy» de `clock.now()` y nunca de `datetime.now()`; devuelve solo `employee_id`, `name`, `start_date`, `status`, `years_of_service`, `days` y `note`, sin `department` ni `role`. Un id inexistente o una `start_date` ilegible da `{"error": "empleado no encontrado"}` | `app/vacations.py`: `VacationBook.vacation_days`; `app/directory.py`: `Directory.find`; `app/main.py`: `create_app` pasa `clock` al `RequestPipeline` | `tests/test_vacations.py::test_an_active_employee_gets_exactly_the_documented_fields`, `test_the_anniversary_day_adds_a_year_according_to_the_injected_clock`, `test_an_employee_in_the_first_year_gets_no_days_and_a_note`, `test_an_inactive_employee_gets_no_days_and_a_note`, `test_an_unknown_employee_is_reported` y `test_vacation_days_follow_the_policy_table` |
| **Cálculo en código, no en el modelo:** con `rule:policy_employee` el orquestador ejecuta `search_policy("vacaciones")` y `vacation_days(<id>)` antes de la primera llamada al modelo; las dos dejan `audit` `tool_call` y cuentan en `tools_used` | `app/orchestrator.py`: `RequestPipeline._prefetch`; `app/agent.py`: `prefetch_list`, `Agent._start_messages` | `tests/test_vacations.py::test_vacations_by_employee_are_looked_up_in_code_before_the_question`; escenario «Vacation days of an employee written another way are computed in code» |
| **Números de `vacation_days` en el revisor:** valen por valor, sin ceros a la izquierda (`0004` y `4` son el mismo), todos los números de todos los campos del resultado. Si el modelo escribe otro número, la respuesta se cambia por `vacation_sentence` («<name> (<employee_id>) tiene <years_of_service> años de servicio y le corresponden <days> días hábiles de vacaciones.», más `note` si no es vacía), armada en código, y se registra `ungrounded` con `policy_number` | `app/reviewer.py`: `allowed_numbers`, `_number_value`, `Reviewer._ground`; `app/vacations.py`: `vacation_sentence` | `tests/test_reviewer.py::test_numbers_from_vacation_days_are_allowed_in_a_policy_answer` y `test_an_invented_number_is_replaced_by_the_vacation_sentence_with_its_note`; escenarios «An invented number of vacation days is replaced by the computed sentence» y «An inactive employee gets no vacation days» |
| **Sin id, la regla completa:** `POLICY_PROMPT` pide no negarse, responder con la regla de la política y sugerir preguntar con el id; con `rule:policy` la política ya está consultada en código | `app/prompts.py`: `POLICY_PROMPT`; `app/llm.py`: `FakeModel._policy_answer` | Escenario «A vacation question without an employee id gets the whole rule» |

## Trade-offs

### Por qué expresiones regulares y no un modelo de PII

- **Determinismo y pruebas.** La misma entrada da siempre la misma salida. Cada tipo tiene un caso positivo y uno
  negativo, y la prueba de concurrencia puede contar exactamente 20 eventos `pii`. Con un modelo, el resultado varía
  y la prueba se vuelve probabilística.
- **Privacidad.** Detectar PII con un servicio externo obliga a mandarle el texto original, que es justo lo que se
  quiere evitar. `redact_pii` corre en el proceso y no usa red.
- **Costo y latencia.** Las expresiones regulares tardan microsegundos y no suman tokens ni afectan el SLO de p95.
- **Alcance acotado.** La spec define cinco tipos con formato fijo (correo, teléfono de 10 dígitos, tarjeta con
  Luhn, CURP y RFC). Para formatos fijos, una expresión regular es la herramienta exacta; un modelo serviría para PII
  sin formato (direcciones, nombres de terceros), que este producto no busca porque los nombres son el negocio.
- **Precio que se paga:** solo se detecta lo que tiene forma conocida. Ver abajo.

### Falsos positivos posibles

- **`phone`:** cualquier número de 10 dígitos seguidos (un folio, una cuenta, un número de pedido) se oculta. Los
  datos del directorio no tienen números así, por eso no afecta las respuestas actuales.
- **`card`:** un número de 13 a 19 dígitos que por casualidad pasa Luhn (aproximadamente 1 de cada 10 números al
  azar) se oculta aunque no sea tarjeta.
- **`rfc` y `curp`:** un código interno con 4 letras, 6 dígitos y 3 caracteres se ve como RFC. El `id` del
  directorio (`EMP-0001`) no coincide porque tiene guion y 4 dígitos.
- **Secretos:** si una clave de `API_KEYS` es una palabra común, cualquier respuesta que la contenga se marca como
  `[REDACTED:secret]`. La compliance exige 16 caracteres o más en producción, lo que lo hace muy improbable.
- **Inyección:** «actúa como» o «system prompt» pueden aparecer en una pregunta legítima («¿Quién actúa como jefe de
  Ventas?»). Como solo se audita, el costo es ruido en `security.injection`, no una respuesta negada.
- **Argumentos:** un nombre real de más de 80 caracteres se rechaza; el agente recibe el error y puede intentar con
  el `id`. `vacation_days` rechaza un nombre: solo acepta `EMP-####`.
- **Comprobación contra las políticas:** cualquier número de la respuesta que no esté en el texto de la política la
  reemplaza, aunque sea legítimo: una fecha que el modelo agrega, un «2» de «2 opciones», el número de un `EMP-dddd`
  o un número escrito por la persona en su pregunta. El costo es una respuesta más larga (el texto de la política),
  no una respuesta falsa.
- **Normalización de ids (Adenda 1):** «emp» o «empleado» seguido de un número que no es un id se convierte en id
  («el empleado 2 de Ventas» pasa a `EMP-0002`; «emp 2021» pasa a `EMP-2021`). Si además menciona «vacaciones», la
  pregunta va a `policy` con `rule:policy_employee` y se calculan los días de ese id.
- **Regla `rule:policy_employee`:** una pregunta de directorio con id que menciona «vacaciones» («¿EMP-0004 está de
  vacaciones?») va a `policy` y responde los días que le corresponden, no si está de vacaciones.

### Falsos negativos posibles

- **Teléfonos** con paréntesis (`(55) 1234 5678`), con puntos, con lada de otro país o con 8 dígitos locales.
- **Correos ofuscados** (`ana arroba empresa punto com`, `ana [at] empresa.com`).
- **Tarjetas** escritas con otros separadores, partidas en dos mensajes o que no pasan Luhn por un error de dedo.
- **RFC de persona moral** (12 caracteres) y CURP con errores de formato.
- **PII sin formato fijo:** direcciones, nombres de familiares, datos de salud. Están fuera del alcance de la spec.
- **Secretos** que el modelo devuelve transformados (en base64, separados por espacios o en partes): `redact_secrets`
  solo busca el valor exacto.
- **Inyección** con frases que no están en la lista, en otros idiomas, parafraseadas o codificadas.
- **Comprobación contra los datos:** solo se comprueban ids `EMP-dddd` y números escritos con dígitos. Pasan sin
  revisar: un número escrito con letras («cinco días»), un número que sí está en la política pero en otro contexto
  (decir «20 días de aguinaldo» cuando el 20 de la política es la fecha límite de pago), un nombre de empleado
  inventado sin id, o un id que existe pero no corresponde a la persona por la que se preguntó. Las respuestas de
  `directory` no se comparan contra políticas, así que una política inventada por ese especialista no se detecta.
- **Números de `vacation_days` (Adenda 1):** se aceptan todos los números de todos los campos del resultado, sin
  mirar a qué campo corresponden. Decir «4 días» de un empleado `EMP-0004`, usar el año o el día de `start_date` como
  días, o el «12» de la nota del primer año como días de alguien que no los tiene, pasa la comprobación. Además se
  suman a los números de la política: un número de la política vale aunque contradiga el cálculo.
- **Ids en otras formas:** «colaborador 4», «el 004», «empleado cuatro» o un id de más de 4 dígitos no se normalizan;
  esas preguntas no activan `rule:employee` ni `rule:policy_employee`.

### Por qué la comprobación contra los datos es en código y no con otro modelo

- Es determinista, gratis y se prueba con resultados exactos, igual que la PII.
- Un segundo modelo revisor costaría una llamada más por petición y también podría equivocarse.
- Ids y números son justo lo que el modelo inventa con más facilidad y lo que más daño hace en RH (días de
  vacaciones, montos, plazos). La comprobación cubre eso y deja lo demás a la validación de salida. Por la misma
  razón, desde la Adenda 1 la antigüedad y los días tampoco los calcula el modelo.

### Por qué la inyección se audita y no se bloquea

- **El daño posible ya está acotado por diseño.** Cada especialista solo tiene sus herramientas de solo lectura
  (dos sobre el directorio, o `search_policy` y `vacation_days` en `policy`), con argumentos validados por
  `validate_tool_args`, y un bucle con tope de pasos. El supervisor solo puede elegir entre dos especialistas. Una
  inyección exitosa no puede escribir, borrar ni llamar a otro sistema; lo peor es una respuesta extraña, que además
  pasa por el `reviewer`.
- **Una lista de frases es fácil de evadir y fácil de disparar por error.** Bloquear con ella castigaría a usuarios
  legítimos (falsos positivos) sin detener a un atacante que cambia una palabra (falsos negativos).
- **La auditoría da la señal que sí sirve:** cuántos intentos hay, de qué cliente y cuándo. Con `security.injection`
  en `/metrics` y el evento en el log, una persona puede revocar la clave de un cliente o bajar su límite.
- **Si el producto crece** (herramientas que escriben, datos más sensibles), la decisión se revisa: el lugar para
  bloquear ya existe en el agente `guard` (`app/guard.py:screen_input`).

### Otros límites conocidos

- **Los runs del especialista sí llevan texto.** `agent_run`, sus runs `llm` y sus herramientas reciben la pregunta
  y el historial ya limpios, y el run `llm` devuelve la salida cruda del modelo, antes del `reviewer`. Por eso, en
  producción, la compliance exige `HIDE_INPUTS=true` y `HIDE_OUTPUTS=true` cuando las trazas están encendidas, y en
  `render.yaml` las trazas vienen apagadas.
- **El mínimo privilegio está en el registro de herramientas, no en el acceso a objetos.** El especialista `policy`
  recibe el `Directory` para validar argumentos y, desde la Adenda 1, `VacationBook` lo lee para calcular días. Con
  `vacation_days`, `policy` puede ver nombre, fecha de ingreso y estado de cualquier `EMP-####`; no recibe el
  departamento ni el puesto.
- **Auditoría desigual entre herramientas.** Como se describe arriba, solo `vacation_days` omite el `audit` cuando
  el formato del argumento es inválido. Quien cuente intentos de herramientas en el log debe sumar `audit` y
  `security` `tool_args`: con `vacation_days` inválido solo aparece el segundo.
- **El resultado de las herramientas** (datos del directorio, textos de políticas y resultados de `vacation_days`)
  sí llega al modelo: es el negocio y no es PII según la spec. Cuando el `reviewer` reemplaza una respuesta por el
  texto de la política o por `vacation_sentence`, ese texto ya no pasa de nuevo por `screen_answer` (es un dato
  propio), solo por el recorte.
- **Estado por proceso:** métricas y límite viven en memoria (ADR 0005 y ADR 0011). Con varias copias del servicio,
  el límite real es `RATE_LIMIT_PER_MINUTE` por copia; el contenedor arranca un solo proceso uvicorn.
- **Sin rotación ni revocación en caliente de claves:** cambiar `API_KEYS` requiere reiniciar el servicio.
