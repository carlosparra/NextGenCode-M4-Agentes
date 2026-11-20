# 0006. Modelo real a través de Cloudflare AI Gateway

## Contexto

La sesión 3 agrega el modelo real (`MODEL_PROVIDER=gateway`). El agente no debe cambiar (ADR 0002), las
pruebas no deben usar la red y el token de Cloudflare es secreto. Esto reemplaza la restricción del ADR 0004
que solo admitía `fake`.

## Decisión

`GatewayModel(name, config, http_client)` implementa `complete(messages)` con `httpx`: antepone su propio
mensaje de sistema con el protocolo JSON, manda `model`, `messages`, `max_tokens` y `temperature`, agrega
`cf-aig-cache-ttl` si `CACHE_TTL_SECONDS > 0` y devuelve `ModelReply` con tokens de `usage` y
`cached = (cf-aig-cache-status == "HIT")`. Cualquier fallo (red, tiempo, estado no 2xx, cuerpo incompleto)
se convierte en `ModelUnavailableError`, que la API traduce a `502 {"detail": "model unavailable",
"request_id"}`. Con `gateway`, `config.py` exige las tres variables `CF_*` al arrancar.

## Consecuencias

- El mensaje de sistema vive en el proveedor, así que el conteo de tokens del `FakeModel` no cambia.
- Las pruebas inyectan `httpx.MockTransport`; ninguna prueba toca Cloudflare.
- El token solo se lee del entorno, no aparece en `repr` ni en el log.
