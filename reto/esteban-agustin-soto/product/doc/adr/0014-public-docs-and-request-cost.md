# 0014. Documentación de la API pública y costo por petición en el log

## Contexto
Para revisar la API sin leer el código hace falta una documentación OpenAPI completa, y para saber cuánto se gasta hace falta sumar el costo desde los logs de Render. Hoy el agente emite `agent_run` sin conocer los precios, y `main.py` calcula el costo después con `_request_cost`; sumar el costo desde el log exigiría calcularlo por un segundo camino.

## Decisión
- El costo se calcula una sola vez, dentro de `Agent.run`, con una función `cost_fn` opcional que `main.py` arma con `_request_cost`, la tabla de precios y el modelo elegido. El resultado se guarda en `AgentResult.cost_usd`, se agrega al evento `agent_run` como `cost_usd` (número) y `main.py` lo reutiliza para la respuesta de `/ask` y para `/metrics`. Sin `cost_fn` el evento no cambia. Un modelo sin precio sigue dando error, no 0.
- `/docs`, `/redoc` y `/openapi.json` son públicos, sin clave y sin variable para apagarlos: el esquema describe rutas y formas, no secretos ni datos de personas, y los ejemplos usan `EMP-0004`.
- Los metadatos, los modelos y las respuestas por ruta viven en `app/api_docs.py`, que solo describe y no cambia el comportamiento; `main.py` los importa.
- El esquema documenta las rutas, la petición, la respuesta real de `/ask` con todos sus campos y los errores `401`, `422`, `429` y `502`. Para no filtrar ni alterar la respuesta no se usa `response_model`: el modelo va solo en `responses`. El encabezado `X-API-Key` se declara con `APIKeyHeader(auto_error=False)` para el botón de autorizar; la autenticación sigue en `require_client`, así que el `401` no cambia.

## Consecuencias
- El costo en el log, en `/ask` y en `/metrics` sale del mismo número; se puede sumar `cost_usd` de `agent_run` en Render.
- Con un modelo sin precio el error ocurre antes de emitir `agent_run`, así que ese evento no sale en ese caso.
- Cualquiera puede ver la forma de la API sin clave; llamar a `/ask` y `/metrics` sigue pidiendo clave.
- El esquema puede alejarse de la respuesta real; una prueba compara los campos de ambos.
- `/docs` carga su interfaz de un CDN; sin red, `/openapi.json` sigue disponible.
