persona

Qué falló: la prueba de humo no llegó a contactar el servicio. `verification/production.py` termina con código 2 y
muestra el mensaje de uso porque `SMOKE_API_KEY` está vacía en el proceso (líneas 37-40). No se probó `/health`,
`/ask` ni `/metrics`, así que esto no dice nada del código, del Dockerfile, de render.yaml ni de Render.

Causa más probable: la variable se definió con `! export SMOKE_API_KEY=...` en el prompt de Claude Code. Cada comando
corre en una shell nueva y la variable exportada no pasa a la siguiente. No es un fallo del producto: no hay nada que
security ni deploy deban cambiar.

Qué tiene que hacer la persona:
1. Correr la prueba en un solo comando, en su propia terminal (no en el chat), para que la variable y la prueba
   compartan la misma shell. Por ejemplo, leer la clave sin que quede en el historial:
   `read -s SMOKE_API_KEY && export SMOKE_API_KEY && uv run python -m verification production https://hr-assistant-m1rp.onrender.com`
2. Usar una clave que esté en `API_KEYS` en Render > Environment del servicio hr-assistant (la parte después de
   `cliente:`), con al menos 16 caracteres. No escribirla en el chat ni en ningún archivo del repositorio.
3. Si después de eso falla un paso concreto (`[FAIL]` en /health, /ask o /metrics), volver a llamar a triage con esa
   salida. Antes, confirmar en Render que el servicio está Live con el commit bdcce85; el primer intento puede tardar
   hasta un minuto si el servicio estaba dormido.
