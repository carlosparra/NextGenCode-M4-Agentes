# 0010. Una clave por cliente, validada en una dependencia

Estado: propuesto

## Contexto

El producto se publica en Internet. `POST /ask` gasta cuota del modelo y `GET /metrics` muestra datos de operación:
no pueden quedar abiertos. Hace falta saber qué cliente hizo cada petición sin que la clave aparezca nunca en log,
trazas ni errores.

## Decisión

`API_KEYS` (`cliente:clave,cliente2:clave2`) se lee en `config.py` como pares cliente y `Secret`. Una entrada mal
formada impide arrancar; el error dice el número de entrada y su largo, nunca su valor. `security.ApiKeyRegistry`
resuelve el cliente comparando con `hmac.compare_digest` contra todas las claves. Una dependencia de FastAPI protege
solo `/ask` y `/metrics`, responde `401 {"detail": "invalid or missing API key"}` y deja `request.state.client`.
`/`, `/health`, `/docs` y `/openapi.json` quedan abiertas. El nombre del cliente (no la clave) va en los eventos
`request`, `audit` y `agent_run` y en los metadatos de la traza.

## Consecuencias

- Falla cerrado: con `API_KEYS` vacía, en desarrollo todo `/ask` responde `401` hasta poner una clave local.
- El middleware sigue siendo la capa externa, así que los `401` llevan `X-Request-ID` y quedan en el log.
- Revocar una clave es cambiar `API_KEYS` en Render y reiniciar; no hay base de datos de claves.
- La página guarda la clave en `sessionStorage`: se pierde al cerrar la pestaña, a cambio de no persistirla.
