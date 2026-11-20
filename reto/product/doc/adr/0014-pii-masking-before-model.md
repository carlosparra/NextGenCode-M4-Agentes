# 0014. Datos sensibles enmascarados antes del modelo

Estado: aceptado

## Contexto

El personal de RH puede escribir correos, teléfonos, CURP, RFC, tarjetas o NSS en la pregunta o el historial. Ese
texto llegaría al modelo externo (Cloudflare), al log, a LangSmith y a la caché. El producto no necesita esos datos
para responder: las herramientas buscan por id de empleado o departamento.

## Decisión

- `app/pii.py` detecta `email`, `phone`, `curp`, `rfc`, `card` (Luhn) y `nss` con expresiones regulares compiladas
  una vez. Los solapes se resuelven por prioridad (una CURP no es además RFC; una tarjeta no es teléfono ni NSS).
  `EMP-0004` y fechas no son PII.
- Con `PII_POLICY=mask` (por omisión) cada dato se reemplaza por `[EMAIL]`, `[TELEFONO]`, `[CURP]`, `[RFC]`,
  `[TARJETA]` o `[NSS]` en la ruta `/ask`, después del esquema y la inyección y antes del enrutador, la caché, el
  agente, el log y la traza. La respuesta también se enmascara. Se informa `pii_detected` con los tipos ordenados.
- Con `PII_POLICY=block`, `400 {"detail": "sensitive data not allowed"}`.
- El evento `audit pii_detected` lleva `types` y `where`, nunca el valor. Una pregunta con PII nunca se guarda en
  caché.

## Consecuencias

- Ningún sistema externo ni el log recibe el dato original; se cumple el mínimo de datos.
- Las regex tienen falsos positivos y negativos (formatos raros); se cubren con pruebas positivas y negativas.
- Si el modelo necesitara el dato enmascarado, la respuesta pierde ese detalle; para este producto no aplica.
- `block` es más estricto pero rechaza preguntas legítimas; por eso `mask` es la opción por omisión.

## Nota de vigencia (reto, puntos 5 y 6): sin datos inventados

La decisión sigue vigente. En producción el modelo real inventó un teléfono de un empleado (el directorio no tiene
teléfonos). Se agregan dos capas:

- Prevención: `SYSTEM_PROMPT` (`app/agent.py`) limita la respuesta a los datos de las herramientas, prohíbe
  inventar y, si piden otro dato de una persona, obliga a responder «No tengo ese dato en el directorio.».
- Red de seguridad: el detector `phone` reconoce de 7 a 10 dígitos (juntos o con separadores, `+52` opcional), así
  que un teléfono inventado sale como `[TELEFONO]` en la respuesta, con `audit pii_detected` y `where: answer`.
- Comprobación: pruebas de `tests/test_reto_guardrails.py` y la pregunta por un teléfono en
  `verification production` (`doc/security.md`, "Sin datos inventados").
- Costo: el prompt más largo sube los tokens de entrada de cada llamada (`doc/cost-analysis.md`).
