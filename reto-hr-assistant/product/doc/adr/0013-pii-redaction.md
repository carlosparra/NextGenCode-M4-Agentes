# 0013. Redacción de datos personales en la entrada y en la salida

Estado: propuesto

## Contexto

El personal de RH escribe preguntas que a veces llevan correos, teléfonos, CURP, RFC o tarjetas. Esos datos no deben
llegar al modelo, a la caché del gateway, a la traza ni al log, y el modelo tampoco debe devolverlos. Rechazar la
pregunta (un `4xx`) obligaría a reescribirla aunque casi siempre el dato sobra para responder, y la persona
tendería a reenviarla igual o a quitar el dato de forma inconsistente.

## Decisión

Se **redacta** en vez de rechazar: `app/pii.py` reemplaza cada dato por `[EMAIL]`, `[PHONE]`, `[CURP]`, `[RFC]` o
`[CARD]` antes de enrutar y de llamar al agente, y la respuesta sigue siendo `200` con `pii_redacted` (solo tipos),
para que la página avise qué se ocultó. La pregunta se responde con lo que queda (por ejemplo, el id `EMP-0001`).
Se redactan la pregunta y los turnos del historial; solo la pregunta emite `pii_detected` y suma a las métricas.
El mismo detector filtra la respuesta del modelo. Solo expresiones regulares y código, sin librerías nuevas, en orden
fijo: EMAIL, CARD (13 a 19 dígitos que pasan Luhn), CURP, RFC con homoclave y PHONE (10 dígitos, con espacios,
guiones o `+52`), con límites de dígito para no partir números más largos. Los ids `EMP-0000` no son PII. El evento
`pii_detected` lleva `request_id`, `client`, `direction` y `types`, nunca el valor. `pii_detections` en `/metrics`
cuenta uno por tipo por evento, igual que `types`, no por ocurrencia. En producción `PII_REDACTION=true` es
obligatoria (ADR 0012).

## Consecuencias

- Falsos positivos aceptados: un número de 10 dígitos que no es teléfono (folio, cuenta), un número de 13 a 19
  dígitos que pasa Luhn por casualidad o un código con forma de RFC se oculta; la respuesta puede perder ese dato.
- Falsos negativos aceptados: teléfonos de otros países, con paréntesis o con otra cantidad de dígitos, correos
  ofuscados («ana arroba x»), tarjetas que no pasan Luhn, nombres, direcciones y CLABE. No se detectan; el mínimo
  privilegio de las herramientas (ADR 0014) cubre los datos propios del directorio.
- Agregar un tipo es un patrón, un marcador y sus pruebas, sin tocar el agente.
- Con `PII_REDACTION=false` (solo desarrollo) no se detecta ni redacta, pero el HTML y el recorte de la salida se
  aplican siempre (ADR 0015).
