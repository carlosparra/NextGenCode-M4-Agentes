# ADR 0004: Id por petición y log JSON sin contenido

## Contexto

Soporte necesita responder, con datos, qué pasó con una petición concreta. Hoy no
hay forma de ligar una respuesta con lo que hizo el agente. Las preguntas y
respuestas pueden contener datos personales de empleados.

## Decisión

- Un middleware asigna a cada petición un `request_id`: el del encabezado
  `X-Request-ID` si tiene de 1 a 128 caracteres `[A-Za-z0-9._-]`, o un UUID4 si no
  viene o no es válido. Se devuelve en el encabezado de toda respuesta (incluidas
  422 y 500) y en el cuerpo de `POST /ask`.
- El `request_id` se pasa de forma explícita a `agent.run`, sin variables globales.
- `JsonLogger` escribe una línea JSON por evento en la salida estándar con `ts`
  (ISO 8601 UTC, de un reloj inyectado), `service`, `event` y `request_id`. Eventos:
  `request`, `agent_run`, `audit` y `error`.
- Nunca se registra el texto de la pregunta ni de la respuesta, solo conteos; el
  evento `error` lleva el tipo de la excepción, no su mensaje.

## Consecuencias

- Con un solo id se filtran todas las líneas de una petición en cualquier
  agregador de logs.
- Validar el encabezado evita inyección de líneas en el log, a cambio de no
  respetar ids de cliente con formato raro (se reemplazan).
- Depurar es más difícil sin el texto; se compensa con `steps`, `tools`, `stopped`
  y los eventos `audit`.
