APROBADO

Revisión de QA de la Adenda 1 (vacaciones por empleado) de `spec/06-multiagente.md`.

`uv run python -m verification qa`: `[OK] qa` (pylint 10.00/10).

Lo revisado y por qué no hay incumplimientos claros de QA.md:

- Nombres claros en inglés y funciones cortas con una sola tarea: `app/employee_ids.py` (`canonical_id`,
  `normalize_with_count`, `normalize_employee_ids`), `app/vacations.py` (`years_of_service`, `vacation_days_for`,
  `vacation_sentence`, `VacationBook.vacation_days`), `app/supervisor.py` (`route_by_rules` con la regla
  `rule:policy_employee` antes de `rule:employee`), `app/reviewer.py` (`allowed_numbers`, `_number_value`),
  `app/orchestrator.py` (`_prefetch`) y `app/agent.py` (`prefetch_list`, `_remember`).
- Sin valores fijos sueltos: la tabla de días está en constantes con nombre (`FIRST_TIER_YEARS`, `DAYS_PER_STEP`,
  etc.), y las notas y mensajes son constantes que fija la spec. La spec no pide configuración nueva.
- Determinismo ("no direct datetime.now() usage") e inyección de dependencias: `VacationBook` recibe el `Clock`, y
  `create_app` pasa al `RequestPipeline` el mismo reloj que inyecta. Las pruebas usan `FakeClock`.
- Manejo de errores: un id inexistente o una `start_date` que no se puede leer devuelve
  `{"error": "empleado no encontrado"}`. Un formato inválido no ejecuta la herramienta y registra `tool_args`.
- Docstrings Sphinx en lo público (`:param:`, `:type:`, `:return:`, `:rtype:`).
- Pruebas: `tests/test_employee_ids.py` y `tests/test_vacations.py` cubren lo que pide la Adenda (las formas de
  A1, «2021», el aniversario con reloj fijo, menos de 1 año, baja, inexistente, formato inválido y mínimo
  privilegio).
- README: explica cómo correrlo y documenta la regla nueva, `vacation_days`, el motivo nuevo en `/metrics` y
  `tools_used`. ADR 0014: se actualizó con la Adenda 1 y sigue vigente. `doc/security.md`: agrega los controles y
  los límites conocidos, incluida la auditoría distinta de `vacation_days`.
- Log sin datos personales ni claves: `agent_run` sigue sin texto. El resumen de `guard` solo cuenta
  `ids_normalized` y no repite los ids. `audit` solo registra el `employee_id`, que es dato del directorio.

Sin hallazgos.
