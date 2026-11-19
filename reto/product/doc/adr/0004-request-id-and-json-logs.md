# 0004. Un request_id por petición y log JSON de una línea por evento

Estado: propuesto

## Contexto

Soporte necesita responder "qué pasó con la petición X" con datos. Hoy no hay forma de correlacionar lo que ve
la persona en la página con lo que hizo el agente. El log además no puede llevar datos personales.

## Decisión

- Un middleware HTTP asigna el `request_id`: usa `X-Request-ID` del cliente si cumple
  `^[A-Za-z0-9._:-]{1,128}$`; si no, genera un UUID4. Lo devuelve en el encabezado de toda respuesta y en el
  cuerpo de `POST /ask` y del 500.
- El `request_id` se pasa explícitamente (`request.state` y un emisor ligado por petición), no por variables
  globales.
- `JsonLogger` escribe una línea JSON por evento (`request`, `agent_run`, `audit`, `error`) en un stream
  inyectado (stdout en producción), con `ts` de un reloj inyectado.
- `agent_run` lleva solo conteos; `error` solo el tipo de excepción.

## Consecuencias

- Cualquier línea se filtra por `request_id` con herramientas estándar (`jq`, el agregador de logs).
- Las pruebas leen el log desde un buffer y con hora fija.
- Un id inválido del cliente se reemplaza: el cliente debe leer el id del encabezado de respuesta.
- Agregar un campo con texto libre al log exige revisar este ADR.
