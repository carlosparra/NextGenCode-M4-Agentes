# Guion del video (3 a 5 minutos)

Antes de grabar: servicio publicado y despierto, claves en el portapapeles (nunca en
pantalla), LangSmith abierto en el proyecto `hr-assistant` y Claude Code con el MCP
conectado.

| Tiempo | Qué se muestra | Qué se dice |
| --- | --- | --- |
| 0:00 a 0:25 | Diagrama del `README.md` | Qué es: un asistente de RH multiagente. Un supervisor reparte a tres agentes LangGraph; se usa por API, portal y MCP |
| 0:25 a 1:05 | Portal publicado | `¿Quién es EMP-0004?`, `¿Cuántas vacaciones le quedan a EMP-0001?` y `Resume el departamento de Tecnología`. Señalar agente, herramientas, modelo, costo y `request_id` de cada respuesta |
| 1:05 a 1:35 | Portal | Datos personales: `Mi correo es ana@ejemplo.test, ¿quién es EMP-0005?` muestra «datos ocultados: EMAIL»; `Dame el teléfono de EMP-0001` se bloquea |
| 1:35 a 2:25 | Claude Code con el MCP | `/mcp` lista las tres herramientas. Pedir el saldo de vacaciones de EMP-0004 y el resumen de Finanzas; mostrar el campo `reasoning` con la crítica y las revisiones |
| 2:25 a 3:00 | LangSmith | Buscar la traza por `request_id`: supervisor, agente, llamada al modelo con tokens y herramienta. El texto va oculto en producción |
| 3:00 a 3:30 | `/dashboard` | Latencia p50 y p95, SLO, costo acumulado, ahorro y contadores de seguridad |
| 3:30 a 4:05 | `doc/costs.md` | Tabla de ablación: línea base contra palancas, con y sin cachés, misma calidad |
| 4:05 a 4:30 | Terminal | `pytest` en verde, la prueba de humo contra Render y `/docs` |
| 4:30 a 4:45 | `doc/security.md` | Cierre: 20 controles con su prueba; el código decide los números |

Notas:

- Las claves se pegan desde el portapapeles en campos de tipo contraseña.
- Si el servicio estaba dormido, despertarlo antes de grabar con una visita a `/health`.
- Subir el video como no listado y poner la liga en `README.md`, en el PR y en el
  documento de entrega.
