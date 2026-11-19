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
