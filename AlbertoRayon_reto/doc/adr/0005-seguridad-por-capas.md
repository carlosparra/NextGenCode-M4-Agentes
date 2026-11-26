# ADR 0005: Seguridad por capas y compliance como código

## Contexto

El asistente maneja datos de empleados y se expone en internet, también a hosts MCP.

## Decisión

- Clave por cliente con permisos (`ask`, `mcp`, `metrics`) y límite por minuto.
- Guardas en código antes y después del modelo: inyección, solicitudes de datos
  protegidos y datos personales.
- Las herramientas solo leen, y solo los campos públicos del directorio.
- En producción la aplicación se niega a arrancar con una configuración insegura.

## Consecuencias

- Ninguna protección depende de que el modelo obedezca.
- Las guardas por patrones tienen falsos positivos y negativos; se documentan en
  `doc/security.md` y cada patrón tiene pruebas.
