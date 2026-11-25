# 0001. MCP como adaptador delgado sobre un servicio compartido

- Estado: aceptada
- Fecha: 2026-11-24

## Contexto

El reto pide un servidor MCP cuyas herramientas usen agentes LangGraph, y el curso pide
publicar el HR Assistant como API en producción. Si cada puerta implementa su propia
lógica, los agentes se duplican y las pruebas se multiplican.

## Decisión

- `app/service.py` (`HrService`) concentra los casos de uso: guardas, enrutador, caché,
  métricas, trazas y la invocación de los agentes.
- `app/mcp_server/server.py` solo traduce el protocolo: esquemas de entrada y salida
  (Pydantic), anotaciones (`readOnlyHint`), correlation id, auditoría y errores
  (`ToolError`).
- `app/main.py` hace lo mismo para HTTP.

## Consecuencias

- Las tres herramientas MCP tienen su equivalente REST (`/tools/vacation-balance`,
  `/tools/department-summary`, `/ask`) sin código duplicado.
- Los agentes se prueban sin MCP ni HTTP; el adaptador MCP se prueba con un cliente en
  proceso y con un subproceso stdio real.
- Una nueva puerta (por ejemplo, Slack) cuesta un adaptador, no una reescritura.
