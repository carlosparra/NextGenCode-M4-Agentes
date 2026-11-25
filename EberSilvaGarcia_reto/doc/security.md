# Seguridad

## Activos y amenazas

| Activo | Amenaza | Capa que la frena |
| --- | --- | --- |
| Datos personales de empleados (CURP, RFC, NSS, salario, contacto) | Que el asistente los revele, o que lleguen a logs, trazas o al proveedor del modelo | Minimización en el dominio, guardas de entrada y salida, logs y trazas enmascarados |
| Claves de clientes y del proveedor | Fuga en código, logs, errores o el chat | Variables de entorno, `sync: false` en Render, nunca en logs ni errores, `.gitignore` y `.dockerignore` |
| Cuota y costo del modelo | Abuso o bucles | Límite por cliente, límite del gateway, topes de pasos, de vueltas y de salida |
| Instrucciones del sistema | Inyección de instrucciones y fuga del prompt | Detector de inyección, marcador en el prompt y guarda de salida |
| Integridad de las respuestas | Alucinación de números | Cálculo y verificación por código, `return_direct` |
| Servicio | Arranque con configuración insegura | Compliance como código y `preflight` |

## Controles

| # | Control | Dónde | Prueba |
| --- | --- | --- | --- |
| 1 | Clave por cliente, comparada en tiempo constante (`hmac.compare_digest`); `X-API-Key` o `Authorization: Bearer` | `security/access.py`, `main.py` | `test_keys_and_scopes` |
| 2 | **Permisos por cliente** (`ask`, `mcp`, `metrics`): mínimo privilegio, `403` si no tiene | `config.py::parse_scopes`, `main.py` | `test_keys_and_scopes`, `test_mcp_over_http_needs_a_key_with_mcp_scope` |
| 3 | Límite de peticiones por cliente (ventana de 60 s, `429` + `Retry-After`) | `security/access.py` | `test_rate_limit_returns_429_with_retry_after` |
| 4 | Validación de esquema de toda entrada (largo, roles del historial, patrones); el `422` **no repite** lo recibido | `main.py`, Pydantic | `test_validation_never_echoes_the_input` |
| 5 | Detección de inyección de instrucciones (`400` + auditoría) | `security/guards.py` | `test_prompt_injection_is_rejected` |
| 6 | **Detección de PII** en la pregunta (correo, CURP, RFC, NSS, tarjeta, CLABE, teléfono): se enmascara (`mask`) o se rechaza (`block`) antes del modelo | `security/pii.py`, `guards.py` | `test_pii_is_detected_and_masked`, BDD |
| 7 | Solicitudes de datos protegidos se niegan **sin llamar al modelo** | `guards.py`, `service.py` | `test_personal_data_never_leaves`, BDD |
| 8 | **Validación de salida**: PII y montos enmascarados, fuga del prompt de sistema bloqueada, largo máximo | `guards.py::check_output` | `test_output_guard` |
| 9 | Minimización: el directorio carga la PII pero **solo expone campos de una lista blanca** | `domain/directory.py` | `test_directory_hides_personal_data` |
| 10 | Herramientas de solo lectura, con argumentos validados; las desconocidas se rechazan | `agents/react.py` | `test_unknown_tool_and_bad_args_become_observations` |
| 11 | Subagente **acotado al empleado pedido** (no puede consultar a otros) | `agents/vacation_agent.py` | `test_vacation_agent_cannot_leave_its_scope` |
| 12 | Verificación por código de los números del modelo y `return_direct` | `vacation_agent.py`, `summary_agent.py` | `test_vacation_template_cases`, `test_reflection_falls_back_to_a_template` |
| 13 | **Auditoría** de acciones relevantes (tabla abajo), opcionalmente a un archivo JSONL aparte | `observability/logs.py` | `test_injection_is_rejected_and_audited`, `test_logger_masks_pii_and_writes_audit_file` |
| 14 | **Secretos** solo por entorno; nunca en logs, trazas ni errores; el error de `API_KEYS` dice entrada y largo, nunca el valor | `config.py` | `test_broken_api_keys_never_show_the_value`, contrato del curso |
| 15 | **Compliance como código**: en producción no arranca con modelo simulado, sin claves, con claves cortas o con trazas que muestren texto; el contenedor termina con código 1 | `config.py::check_compliance`, `preflight.py` | `test_production_compliance`, `test_preflight_blocks_bad_production` |
| 16 | Trazas sin texto (`HIDE_*`) o con PII enmascarada | `observability/tracing.py` | `test_trace_payloads_are_hidden_or_masked` |
| 17 | Página: CSP con nonce por petición, `frame-ancestors 'none'`, respuestas con `textContent`, clave en `sessionStorage`; cabeceras `nosniff`, `X-Frame-Options`, `Referrer-Policy`, `no-store` | `main.py`, `static/` | `test_health_ready_and_pages_need_no_key`, e2e |
| 18 | Errores sin detalles internos (`500 internal error` + `request_id`) | `main.py`, `mcp_server/server.py` | `test_unexpected_errors_return_500_without_details`, `test_model_and_internal_failures` |
| 19 | MCP: clave y permiso en `/mcp`, protección contra DNS rebinding (hosts y orígenes permitidos), anotaciones de solo lectura | `main.py`, `mcp_server/` | `test_mcp_over_http_needs_a_key_with_mcp_scope` |
| 20 | Contenedor sin root (uid 10001), código de solo lectura para el proceso, imagen mínima sin herramientas de prueba; gateway autenticado y token con permisos mínimos; CI con gitleaks y pip-audit | `Dockerfile`, `render.yaml`, `ci.yml` | `podman exec ... id`, evidencia |

## Auditoría

| Acción | Cuándo |
| --- | --- |
| `auth_failed` | Clave ausente o inválida |
| `forbidden` | Clave válida sin el permiso de la ruta |
| `rate_limited` | Se excedió el límite |
| `input_rejected` | Inyección, PII con `block` o pregunta vacía (con el motivo) |
| `pii_detected` | PII en la entrada o en la salida (solo los tipos, nunca el valor) |
| `protected_data_request` | Se pidió un dato protegido |
| `tool_call` | Cada herramienta que ejecuta un agente, con argumentos validados |
| `tool_rejected` | Herramienta inexistente, argumentos inválidos o fuera de alcance |
| `output_corrected` | El código reemplazó la explicación del modelo |
| `output_blocked` | La respuesta intentó revelar el prompt de sistema |
| `agent_self_correction` | Se pidió al modelo usar una herramienta |
| `mcp_tool_call` | Cada llamada MCP con su estado |

Cada registro lleva `ts`, `request_id`, `client` y `channel`.

## Gestión de secretos

- Locales: `.env` (en `.gitignore` y `.dockerignore`, permisos 600). Plantilla sin valores
  en `.env.example`.
- Producción: Render > Environment, con `sync: false` en el blueprint.
- La página no guarda la clave en el código ni en `localStorage`.
- Los scripts leen claves de variables (`SMOKE_API_KEY`, `LOAD_API_KEY`, `MCP_API_KEY`),
  nunca de argumentos, que quedarían en el historial.
- Rotación: se agrega la nueva clave a `API_KEYS`, se migra el cliente y se quita la vieja,
  sin tiempo fuera.

## Limitaciones

- Los detectores son expresiones regulares: un CURP con espacios o un teléfono escrito con
  palabras pasan. Mejora: un clasificador de PII (por ejemplo, Presidio) en la misma guarda.
- El detector de inyección es por patrones conocidos; la defensa real son las capas que
  siguen (herramientas de solo lectura, minimización, guardas de salida).
- El límite de peticiones es por proceso.
