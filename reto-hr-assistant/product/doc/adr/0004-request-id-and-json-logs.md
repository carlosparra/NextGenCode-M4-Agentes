# 0004. Id por petición y log JSON de eventos sin contenido

Estado: propuesto

## Contexto

Soporte necesita responder "qué pasó con la petición X" con datos. Hoy no hay forma de ligar una respuesta con
lo que hizo el agente. El log no puede guardar preguntas ni respuestas (datos de empleados) y las pruebas deben
ser deterministas aunque el log lleve la hora.

## Decisión

Un middleware HTTP resuelve el `request_id`: usa `X-Request-ID` si cumple 1 a 128 caracteres `[A-Za-z0-9._-]`,
si no genera un UUID4. Lo devuelve en el encabezado de toda respuesta y en `request_id` de `POST /ask`.
`JsonLogger` escribe en la salida estándar una línea JSON por evento con `ts` (UTC, ISO 8601), `service`,
`event` y `request_id`. Eventos: `request`, `agent_run` (solo conteos y `stopped`), `audit` (una por
herramienta) y `error` (solo el tipo). El middleware es el único punto que atrapa excepciones y responde
`500 {"detail": "internal error", "request_id"}`. La hora llega por un `Clock` inyectado; `SystemClock` es el
único que lee la hora real. El agente no conoce el log: avisa cada herramienta con un callback.

## Consecuencias

- Con un `request_id` se filtran todas las líneas de una petición en cualquier copia.
- Un id del cliente con formato raro se reemplaza, así que el cliente no puede inyectar encabezados ni líneas.
- `audit` lleva los argumentos (id o departamento); si algún día hay herramientas con texto libre habrá que
  revisarlo.
- Las pruebas inyectan reloj falso y un flujo en memoria; no dependen de la hora ni de la consola.
