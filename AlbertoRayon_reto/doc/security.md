# Seguridad

Ninguna protección depende de que el modelo obedezca: todas son código que corre
antes o después del modelo.

## Controles

| # | Control | Dónde | Prueba |
| --- | --- | --- | --- |
| 1 | Validación de entrada: tipos, largo de la pregunta, roles y tamaño del historial | `app/main.py` (`AskRequest`, `ask`) | `test_invalid_requests_get_422_without_echoing_the_input` |
| 2 | Errores que no devuelven la entrada ni detalles internos (`422`, `500`, `502`) | `app/main.py` | `test_unexpected_errors_become_a_generic_500` |
| 3 | Detección y enmascarado de datos personales en la pregunta y el historial: correo, CURP, RFC, tarjeta (con Luhn), CLABE, NSS y teléfono | `app/pii.py`, `app/guards.py` | `test_personal_data_is_detected_and_masked`, `test_personal_data_never_reaches_the_model` |
| 4 | Bloqueo de solicitudes de datos protegidos de terceros | `app/guards.py` (`PROTECTED_REQUEST`) | `test_input_guard_blocks` |
| 5 | Bloqueo de inyección de prompts, también en el historial | `app/guards.py` (`INJECTION`) | `test_injection_in_history_is_blocked` |
| 6 | Validación de salida: datos personales, filtración del prompt de sistema (marcador canario) y largo máximo | `app/guards.py` (`check_output`) | `test_output_guard_protects_the_answer` |
| 7 | Clave por cliente, comparada en tiempo constante | `app/access.py` (`Authenticator`) | `test_missing_or_wrong_key_returns_401` |
| 8 | Mínimo privilegio por cliente: permisos `ask`, `mcp` y `metrics` | `app/config.py`, `app/main.py` (`gate`) | `test_scopes_enforce_least_privilege` |
| 9 | Límite de peticiones por cliente, con `429` y `Retry-After` | `app/access.py` (`RateLimiter`) | `test_rate_limit_returns_429_with_retry_after` |
| 10 | Mínimo privilegio de los agentes: herramientas de solo lectura que solo ven los campos públicos | `app/directory.py` (`PUBLIC_FIELDS`) | `test_directory_never_exposes_personal_fields` |
| 11 | Gestión de secretos: solo por variables de entorno; nunca en el código, el log ni los errores | `app/config.py`, `.env.example`, `render.yaml` | `test_api_keys_error_never_shows_the_value`, `test_key_never_appears_in_logs` |
| 12 | Compliance como código: en producción no arranca con una configuración insegura | `app/config.py` (`check_compliance`), `app/preflight.py` | `test_production_refuses_unsafe_configuration` |
| 13 | Registro de auditoría de las acciones relevantes | `app/logs.py`, `app/service.py`, `app/main.py` | `test_logs_are_json_without_the_question_text` |
| 14 | Trazas sin contenido en producción | `app/tracing.py`, `check_compliance` | `test_production_refuses_unsafe_configuration` |
| 15 | Cabeceras de seguridad y política de contenido con nonce en las páginas | `app/main.py` (`page`, middleware) | `test_pages_are_served_with_a_strict_content_policy` |
| 16 | Servidor MCP remoto con clave, permiso propio y lista de hosts permitidos | `app/mcp_server.py` (`http_app`) | `test_remote_mcp_needs_a_key_and_answers_over_http`, `test_remote_mcp_rejects_unknown_hosts` |
| 17 | Topes en todo bucle de agente | `app/agents/` | `test_step_cap_stops_the_loop`, `test_reflection_falls_back_to_verified_facts` |
| 18 | Cifras verificadas en código | `app/vacations.py`, `app/agents/summary.py` | `test_vacation_balance_overrides_an_invented_number` |
| 19 | Contenedor con usuario sin privilegios y código de solo lectura | `Dockerfile` | [`../evidence/container.txt`](../evidence/container.txt) |
| 20 | El portal guarda la clave en `sessionStorage` y pinta las respuestas con `textContent` | `app/static/index.html` | `test_pages_are_served_with_a_strict_content_policy` |

## Datos personales

El archivo `data/employees.json` trae datos personales ficticios (correo, teléfono y
RFC) para que la protección sea real y no decorativa. Hay tres barreras:

1. **Al cargar:** `Directory.from_file` descarta todo campo que no esté en
   `PUBLIC_FIELDS`. Los agentes no pueden leer lo que nunca se cargó.
2. **A la entrada:** si la persona escribe un dato personal, se reemplaza por un
   marcador como `[EMAIL]` antes de llegar al modelo, al log o a la traza. Si pide el
   dato protegido de otra persona, la petición se bloquea con `400`.
3. **A la salida:** si aun así una respuesta trae un dato personal, se enmascara y se
   registra en la auditoría.

Distinción importante: «mi teléfono es 55 5550 0101» no es una solicitud, así que se
enmascara y la pregunta sigue; «dame el teléfono de EMP-0001» sí lo es, y se bloquea.

## Auditoría

Eventos `audit` del log, todos con `request_id`, `client` y `channel`:

| `action` | Cuándo |
| --- | --- |
| `auth_failed` | Clave ausente o inválida |
| `scope_denied` | La clave no tiene el permiso de la ruta |
| `rate_limited` | El cliente pasó su límite |
| `guard_blocked` | La guarda de entrada bloqueó la petición, con el motivo |
| `pii_masked` | Se enmascararon datos personales, con los tipos (nunca el valor) |
| `delegate` | El supervisor eligió un especialista |
| `tool_call` | Un agente usó una herramienta, con sus argumentos |
| `model_nudged` | El modelo respondió sin el formato pedido y se le pidió corregir |
| `verified_override` | Se reemplazó una cifra del modelo por el valor verificado |
| `summary_fallback` | El resumen no pasó la crítica y se entregaron los hechos |
| `output_guard` | La guarda de salida modificó una respuesta |

## Mínimo privilegio

- **Clientes:** en producción cada cliente necesita permisos explícitos en
  `CLIENT_SCOPES`. El portal solo pregunta (`ask`), el host MCP solo usa `/mcp` y el
  monitoreo solo lee `/metrics`. Una clave filtrada del tablero no puede preguntar.
- **Agentes:** cada agente tiene solo sus herramientas, todas de lectura.
- **Tokens externos:** el token de Cloudflare solo necesita Workers AI, y la clave de
  LangSmith puede ser de tipo solo trazas.
- **Contenedor:** usuario `hr` sin privilegios y sin shell; `/srv` no se puede escribir.

## Límites conocidos

- Las guardas son patrones: pueden dejar pasar una inyección redactada de forma
  nueva y bloquear una pregunta legítima que se parezca a una solicitud de datos. Por
  eso son una capa más y no la única: aunque una inyección pase, las herramientas no
  pueden entregar datos que no cargaron.
- El límite de peticiones es por proceso; ver `architecture.md`.
- El transporte stdio no pide clave: corre en la máquina de quien lo lanza, con sus
  permisos.
