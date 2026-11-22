# Reto · Multiagente en producción: vacaciones, resumen por área y protección de datos personales

Parte del producto de las sesiones 1 a 4, ya publicado en Render. Lo extiende con dos herramientas nuevas y le agrega
una capa de protección de datos personales (PII) en la entrada y en la salida. Todo lo anterior sigue igual: clave por
cliente, límite de peticiones, compliance, trazas, métricas, enrutamiento, caché, contenedor, CI y Render.

La idea de costo se mantiene: **el código hace la chamba y el modelo solo elige la herramienta y redacta**. Las
herramientas nuevas devuelven datos ya calculados para que el modelo no tenga que sumar ni filtrar.

## Lo que debe hacer

1. **Datos nuevos.** `spec/employees.json` agrega a cada empleado:
   - `vacation_days_total` y `vacation_days_taken` (enteros).
   - `personal_email` y `personal_phone`: datos personales que **ninguna herramienta devuelve nunca**.

   `get_employee` y `search_by_department` siguen devolviendo solo id, nombre, departamento, puesto, fecha de
   ingreso y estado. Cada herramienta tiene una **lista explícita de campos permitidos** (mínimo privilegio): un campo
   nuevo en los datos no aparece en ninguna respuesta hasta que alguien lo agregue a esa lista.
2. **Herramienta `get_vacation_balance(employee_id)`.** Devuelve nombre, días totales, días tomados y días
   disponibles (`total - tomados`, calculado en código). Un id que no existe da el mismo mensaje que `get_employee`.
   Un empleado con estado `baja` responde que ya no tiene saldo de vacaciones.
3. **Herramienta `department_summary(department)`.** Devuelve, calculado en código, cuántas personas hay en el
   departamento, cuántas están activas y cuántas de baja, y el promedio de días de vacaciones disponibles de las
   activas (un decimal). El departamento se compara sin importar mayúsculas ni acentos. Un departamento que no existe
   lista los departamentos válidos.
4. **El agente conoce las cuatro herramientas.** El prompt del sistema las describe en una línea cada una, con sus
   argumentos. El modelo simulado (`fake`) sabe pedir las dos nuevas:
   - «¿Cuántos días de vacaciones le quedan a EMP-0004?» → `get_vacation_balance`.
   - «Dame el resumen del departamento de Ventas» → `department_summary`.
5. **Detección de PII en la entrada** (`app/pii.py`, sin librerías nuevas, solo expresiones regulares y código):
   - Detecta correos electrónicos, teléfonos de 10 dígitos (con o sin espacios, guiones o `+52`), CURP, RFC con
     homoclave y números de tarjeta de 13 a 19 dígitos que pasan el algoritmo de Luhn.
   - Los ids `EMP-0000` **no** son PII.
   - Antes de mandar la pregunta al modelo, cada dato se reemplaza por `[EMAIL]`, `[PHONE]`, `[CURP]`, `[RFC]` o
     `[CARD]`. El modelo, la caché, la traza y el log nunca ven el valor original.
   - La respuesta a `/ask` sigue siendo `200`; el campo nuevo `pii_redacted` lista los tipos encontrados en la
     pregunta (por ejemplo `["EMAIL"]`), sin valores. Lista vacía si no hubo.
6. **Validación y filtro de la salida.**
   - La respuesta del modelo pasa por el mismo detector antes de llegar al cliente; cualquier PII se reemplaza igual
     que en la entrada.
   - La respuesta se recorta a `MAX_ANSWER_CHARS` caracteres y se le quitan etiquetas HTML, para que la página nunca
     pinte HTML que venga del modelo.
   - Si después del filtro la respuesta queda vacía, se responde «No tengo una respuesta para eso.»
7. **Auditoría.** Cada vez que se detecta PII se escribe un evento `pii_detected` en el log JSON con `request_id`,
   `client`, `direction` (`input` u `output`) y `types`. **Nunca el valor detectado.** Los eventos `audit` de las
   herramientas nuevas son iguales a los de las existentes.
8. **Métricas.** `GET /metrics` agrega `pii_detections` con un conteo por dirección y por tipo, por ejemplo
   `{"input": {"EMAIL": 2}, "output": {}}`.
9. **Compliance.** Con `ENVIRONMENT=production`, el producto no arranca si `PII_REDACTION` no vale `true`. La regla
   se agrega a `doc/compliance-checklist.md`.
10. **Documentación.**
    - ADR `0013-pii-redaction.md`: por qué se redacta (en vez de rechazar la pregunta), qué tipos se cubren y qué
      falsos positivos y negativos se aceptan.
    - ADR `0014-least-privilege-tools.md`: listas de campos permitidos por herramienta y cálculo en código.
    - `doc/architecture.md` agrega las herramientas y la capa de PII al diagrama.
    - `README.md` agrega las variables nuevas.

## Pruebas de punta a punta (las actualiza `qa-e2e`)

- Preguntar «¿Cuántos días de vacaciones le quedan a EMP-0004?» muestra un número de días.
- Preguntar algo con un correo (por ejemplo «mi correo es ana@example.com, ¿quién es EMP-0001?») responde y la
  página nunca muestra `ana@example.com`.

## Conjunto de evaluación

`verification/eval_set.json` suma tres preguntas: una de vacaciones, una de resumen por departamento y una con PII
que debe responderse sin repetir el dato. La comparación de costo contra la sesión 3 se mantiene: misma calidad,
costo por respuesta igual o menor.

## Configuración nueva

| Variable | Por omisión | Para qué |
| --- | --- | --- |
| `PII_REDACTION` | `true` | Redacta PII en preguntas y respuestas. En producción es obligatoria |
| `MAX_ANSWER_CHARS` | `1500` | Largo máximo de la respuesta que llega al cliente |

## Cómo se comprueba

- `verification unit`, `contract`, `qa`, `e2e` y `evaluate`, como en la sesión 4.
- Una persona aprueba la publicación. Render redespliega con el push.
- `uv run python -m verification production <url>`: la prueba de humo contra Render sigue pasando.
