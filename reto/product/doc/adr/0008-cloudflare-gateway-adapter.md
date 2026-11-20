# 0008. Modelo real como adaptador de AI Gateway con cliente HTTP inyectado

Estado: propuesto

## Contexto

Llega el modelo real: Cloudflare Workers AI a través de AI Gateway, con token secreto. Las pruebas no deben
usar red ni gastar cuota, y un fallo del proveedor no debe verse como error interno.

## Decisión

- `gateway.GatewayLLM` cumple el protocolo `LLM` y usa un `httpx.Client` inyectado (`MockTransport` en pruebas).
- Manda `{model, messages, max_tokens, temperature}` con `MODEL_MAX_TOKENS` y `MODEL_TEMPERATURE`; lee tokens de
  `usage` y el estado de caché de `cf-aig-cache-status`.
- Timeout fijo y sin reintentos automáticos. Todo fallo se convierte en `ModelUnavailable`, que la API traduce
  a `502 {"detail": "model unavailable", "request_id"}` con evento `error` (solo el tipo).
- Con `MODEL_PROVIDER=gateway`, faltar `CF_ACCOUNT_ID`, `CF_GATEWAY_ID` o `CF_API_TOKEN` impide arrancar.
  El token se guarda con `repr=False` y nunca se escribe en log, traza ni mensaje de error.

## Consecuencias

- El agente y la API no saben qué proveedor hay detrás; `fake` sigue siendo el valor por omisión.
- Un proveedor caído produce 502 rápido y visible en `error_rate`, en lugar de 500 o esperas largas.
- Sin reintentos, un fallo pasajero llega a la persona; se prefiere a pagar llamadas repetidas.

## Nota de vigencia (reto, triage ciclo 2): gateway autenticado

La decisión sigue vigente, con un agregado: el AI Gateway de producción tiene "Authenticated Gateway" encendido,
así que el adaptador ahora también se autentica contra el gateway.

- Variable nueva `CF_AIG_TOKEN`, opcional. Con valor, `GatewayLLM` manda `cf-aig-authorization: Bearer <token>`
  (constante `GATEWAY_AUTH_HEADER` en `app/gateway.py`) además de `Authorization` con `CF_API_TOKEN`. Vacía, el
  encabezado no se manda y un gateway sin autenticación sigue funcionando igual.
- Es secreto como `CF_API_TOKEN`: `repr=False` en `app/config.py`, `sync: false` en `render.yaml`, nunca en log,
  traza ni error. Es un token separado, solo con el permiso `AI Gateway: Run` (`doc/security.md`).
- Si el gateway exige el token y falta o es inválido, Cloudflare responde 401 y el producto da 502, igual que
  cualquier otro fallo del proveedor; `verification production` lo detecta.
- Límite aprendido: `ModelUnavailable` no registra el código de estado de Cloudflare, así que un 401 por
  configuración (por ejemplo, un valor pegado con comillas en Render) se ve igual que una caída
  (`doc/observability.md`).
