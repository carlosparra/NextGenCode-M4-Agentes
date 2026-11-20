# ADR 0007: Modelo real por Cloudflare AI Gateway y `complete` que devuelve `Completion`

## Contexto

La sesión 3 agrega un modelo real (Workers AI a través de AI Gateway). Cada llamada debe informar tokens, si vino
de la caché y qué modelo la atendió. Hoy `complete(messages)` devuelve texto y los tokens quedan en atributos de la
instancia del modelo, que se comparte entre peticiones concurrentes. Si el proveedor falla, la API debe responder
502, no 500.

## Decisión

- `complete(messages)` devuelve un `Completion` inmutable: `text`, `input_tokens`, `output_tokens`, `cached`.
  Cada `Model` tiene un `name`. Esto complementa el ADR 0002: la interfaz sigue siendo una sola función.
- `gateway.py` implementa `GatewayModel` con un `httpx.Client` inyectado y un timeout fijo. Agrega el prompt de
  sistema con el protocolo JSON; el agente no cambia de protocolo.
- Toda falla del gateway (red, timeout, status no 2xx, cuerpo inválido) se convierte en `ModelUnavailable`;
  `main.py` la traduce a `502 {"detail": "model unavailable", "request_id"}` y registra solo el tipo de error.
- Con `MODEL_PROVIDER=gateway`, faltar `CF_ACCOUNT_ID`, `CF_GATEWAY_ID` o `CF_API_TOKEN` impide arrancar. El
  token se guarda como `SecretStr` y nunca se registra.

## Consecuencias

- Desaparece la condición de carrera de los tokens: cada llamada trae los suyos.
- Hay que actualizar `FakeModel` y las pruebas que leían `model.input_tokens`.
- Las pruebas del gateway usan `httpx.MockTransport`: no tocan la red ni gastan cuota.
- Agregar otro proveedor sigue siendo una clase nueva en `llm.py` o en su propio módulo.
