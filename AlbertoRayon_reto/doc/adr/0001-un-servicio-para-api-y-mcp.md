# ADR 0001: Un solo servicio para la API y el servidor MCP

## Contexto

El reto pide una API REST en producción y un servidor MCP cuyas herramientas usen
agentes LangGraph. Se podían publicar como dos servicios o como uno.

## Decisión

Un solo servicio FastAPI. El MCP por HTTP se monta en `/mcp` en modo sin estado y
comparte proceso, `HRService` y middleware con la API. El mismo módulo corre por
stdio para hosts locales.

## Consecuencias

- Una imagen, un despliegue y una sola capa de seguridad y observabilidad.
- Un host MCP y el portal reciben las mismas guardas, métricas y trazas.
- La API y el MCP escalan juntos; separarlos después solo requiere otro punto de
  entrada sobre `HRService`.
