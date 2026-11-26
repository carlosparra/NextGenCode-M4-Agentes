# Lista de compliance

Cada regla está en el código y tiene una comprobación automática.

| Regla | Dónde está en el código | Cómo se comprueba |
| --- | --- | --- |
| En producción no se usa el modelo simulado | `app/config.py`, `check_compliance` | `test_production_refuses_unsafe_configuration`; contrato `test_production_refuses_the_fake_model` |
| En producción hay claves, de 16 caracteres o más | `app/config.py`, `check_compliance` | `test_production_refuses_unsafe_configuration` |
| En producción cada cliente tiene permisos explícitos | `app/config.py`, `check_compliance` | `test_production_refuses_unsafe_configuration` |
| En producción las trazas no llevan texto | `app/config.py`, `check_compliance` | `test_production_refuses_unsafe_configuration` |
| Una clave mal formada no arranca y no se muestra | `app/config.py`, `parse_api_keys` | `test_api_keys_error_never_shows_the_value`; contrato `test_a_broken_api_keys_never_leaks_the_key` |
| El modelo real exige sus tres variables | `app/config.py`, `check_compliance` | `test_invalid_values_refuse_to_start` |
| La configuración se valida antes de arrancar | `app/preflight.py`, `Dockerfile` (`CMD`) | `test_preflight_explains_why_production_cannot_start` |
| Sin clave no se pregunta ni se leen métricas | `app/main.py`, `gate` | `test_missing_or_wrong_key_returns_401` |
| Cada cliente solo hace lo que su permiso permite | `app/main.py`, `gate` | `test_scopes_enforce_least_privilege` |
| Nadie abusa: límite por cliente | `app/access.py`, `RateLimiter` | `test_rate_limit_returns_429_with_retry_after` |
| Los datos personales no llegan al modelo | `app/guards.py`, `app/service.py` | `test_personal_data_never_reaches_the_model` |
| Los datos personales no salen en una respuesta | `app/guards.py`, `check_output` | `test_output_guard_masks_leaked_personal_data` |
| El log no lleva texto de preguntas ni claves | `app/logs.py`, `app/service.py` | `test_logs_are_json_without_the_question_text`, `test_key_never_appears_in_logs` |
| Las acciones relevantes quedan auditadas | `app/service.py`, `app/main.py` | `test_logs_are_json_without_the_question_text` |
| Las cifras de vacaciones siguen la LFT | `app/vacations.py` | `test_entitlement_follows_the_lft_table` |
| La imagen solo existe si las pruebas pasan | `Dockerfile`, etapa `test` | `docker build` |
| El contenedor no corre como root | `Dockerfile`, `USER hr` | `evidence/container.txt` |
| Los secretos no están en el repositorio | `.gitignore`, `render.yaml` (`sync: false`) | Revisión del diff antes de cada push |
