# Guion del video (4 min 30 s)

Grabar en 1080p con la terminal en letra grande. Antes de grabar:

- El servicio de Render está **Live**: abre la URL una vez para despertarlo.
- `export HR_API_KEY=...` en la terminal, **fuera de cámara**.
- Pestañas abiertas: la página, `/docs`, `/dashboard`, LangSmith (proyecto
  `hr-assistant`) y Cloudflare AI Gateway (`hr-assistant` > Logs).
- En la terminal: `cd EberSilvaGarcia_reto`.

| Tiempo | Pantalla | Qué decir y hacer |
| --- | --- | --- |
| 0:00–0:20 | README (diagrama) | «Este es el HR Assistant convertido en sistema multiagente: un servidor MCP con herramientas que son agentes LangGraph, y la misma lógica publicada como API en Render.» |
| 0:20–1:20 | Claude Code (host MCP) | `claude` en la carpeta; aceptar el servidor `hr-assistant` de `.mcp.json`; `/mcp` muestra las 3 herramientas. Preguntar: «¿Cuántos días de vacaciones le quedan a EMP-0001?». Abrir el resultado de `vacation_balance`: los 3 pasos de `reasoning` (ReAct), los números y `model_answer_kept`. |
| 1:20–2:00 | Claude Code | «Resume el área de Tecnología». Mostrar `critiques`: la primera vuelta pidió la antigüedad promedio y la segunda salió vacía (reflection). Luego «¿Y el área de Marketing?»: error controlado con los departamentos válidos. |
| 2:00–2:40 | Página en Render | Escribir la clave (campo de contraseña). Preguntar por EMP-0004, luego «¿Cuál es el CURP de EMP-0004?» (se niega sin gastar tokens) y una pregunta con un correo propio (se enmascara). Señalar el `request_id`. Una clave mala: «Clave inválida». |
| 2:40–3:20 | LangSmith | Filtrar por el `request_id` de la página: la traza `hr_agent` → `vacation_agent` con los nodos `reason`/`act` y `model.complete` con tokens; los textos están ocultos (producción). Luego Cloudflare AI Gateway: las llamadas, el modelo 8B y los `HIT` de caché. |
| 3:20–3:50 | `/dashboard` | Latencia contra el SLO, costo acumulado, intents, `auth_failed`, `pii_masked_input`. Mencionar `/metrics/prometheus`. |
| 3:50–4:15 | `doc/costs.md` | La tabla del modelo real: misma calidad, −89.2 % de costo y latencia de 3.0 s a 1.3 s. El hallazgo del 8B que inventó «7 días» y cómo `return_direct` lo resolvió. |
| 4:15–4:30 | Terminal | `python scripts/smoke.py <url>`: todo `[OK]`. «Pruebas, decisiones y evidencia en el README. Gracias.» |

## Comandos de respaldo (por si algo falla en vivo)

```bash
python scripts/mcp_demo.py                         # MCP local por stdio, sin host
MCP_API_KEY=$HR_API_KEY python scripts/mcp_demo.py https://hr-assistant-ebersilva.onrender.com/mcp
SMOKE_API_KEY=$HR_API_KEY python scripts/smoke.py https://hr-assistant-ebersilva.onrender.com
```
