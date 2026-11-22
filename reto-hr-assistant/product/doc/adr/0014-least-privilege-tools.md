# 0014. Herramientas con mínimo privilegio y cálculo en código

Estado: propuesto

## Contexto

Los datos de empleados ahora incluyen `personal_email` y `personal_phone`, y `get_employee` devolvía el registro
completo. Además, las preguntas nuevas (saldo de vacaciones, resumen por área) piden restas, conteos y promedios que
un modelo pequeño puede hacer mal y que encarecen cada respuesta si se le pasa la lista completa.

## Decisión

Cada herramienta de `app/directory.py` tiene una **tupla explícita de campos permitidos** y arma su salida solo con
esos campos (`_pick`), nunca copiando el registro:

- `get_employee` y `search_by_department` (`EMPLOYEE_FIELDS`): id, nombre, departamento, puesto, fecha de ingreso y
  estado.
- `get_vacation_balance` (`VACATION_FIELDS`): nombre, días totales y tomados, más `vacation_days_available`
  calculado. Un id inexistente da el mismo mensaje que `get_employee`; un empleado de `baja` responde que ya no tiene
  saldo de vacaciones.
- `department_summary`: solo agregados (departamento, personas, activas, de baja y
  `average_vacation_days_available`), ningún dato de una persona. Un departamento inexistente lista los válidos.

Un campo nuevo en los datos no sale hasta agregarlo a una lista. Los números se calculan en código: disponibles =
total - tomados; el promedio es solo de las activas, con un decimal, y `null` si no hay activas. El departamento se
compara sin mayúsculas ni acentos (`unicodedata`). El modelo solo elige la herramienta y redacta. Las herramientas
nuevas emiten el mismo evento `audit` que las existentes.

## Consecuencias

- Ningún dato personal llega al modelo, la traza ni la respuesta por medio de una herramienta; la redacción de PII
  (ADR 0013) queda como segunda barrera, no como la única.
- Respuestas más cortas y baratas: el modelo recibe el resultado, no la lista para calcularlo.
- Mostrar un campo nuevo es un cambio deliberado, revisable en el diff y con su prueba
  (`tests/test_least_privilege_tools.py`, `tests/features/tools.feature`).
- Las herramientas siguen siendo de solo lectura y devuelven texto (JSON o un mensaje), como en la sesión 1.
