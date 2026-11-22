# 0010. Una clave por cliente en un encabezado

## Contexto
El producto sale a internet y `/ask` cuesta dinero. Hace falta saber quién pregunta, revocar a un cliente sin tocar a otros y no filtrar la clave nunca.

## Decisión
`API_KEYS` (`cliente:clave,...`) se lee del entorno y se guarda con `repr=False`. `POST /ask` y `GET /metrics` exigen `X-API-Key`; la comparación usa `hmac.compare_digest` contra todas las claves. El nombre del cliente va en el log, en la auditoría y en la traza; la clave, en ninguna parte ni en mensajes de error. `/`, `/health` y `/docs` quedan abiertos. Sin claves configuradas, esas rutas responden `401`.

## Consecuencias
- Cada evento se atribuye a un cliente y se puede cortar a uno solo.
- Rotar una clave exige cambiar el secreto en Render y reiniciar.
- Una clave en `sessionStorage` vive solo mientras dura la pestaña.
- Es autenticación simple, no identidad de personas.
