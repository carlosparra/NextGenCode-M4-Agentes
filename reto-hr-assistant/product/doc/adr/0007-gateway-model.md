# 0007. Modelo real a través de AI Gateway, con cliente HTTP inyectado

Estado: propuesto

## Contexto

Llega el modelo real (Cloudflare Workers AI a través de AI Gateway). El agente debe seguir sin conocer HTTP ni
Cloudflare, aunque sí tiene que adaptarse: este ADR reemplaza la parte del ADR 0002 que decía que `agent.py` no
cambia. Las pruebas no pueden usar red, el token de Cloudflare es secreto y una falla del proveedor no debe verse
como un error interno (`500`) del producto.

## Decisión

`GatewayModel(name, gateway_settings, http_client)` en `gateway.py` cumple `complete(messages)`. Hace `POST` a
`.../{CF_ACCOUNT_ID}/{CF_GATEWAY_ID}/workers-ai/v1/chat/completions` con `Authorization: Bearer` y el cuerpo
`{model, messages, max_tokens, temperature}`; lee `usage.prompt_tokens`, `usage.completion_tokens` y
`cf-aig-cache-status`. El cliente `httpx` se inyecta (las pruebas usan `httpx.MockTransport`) y tiene un tiempo
de espera fijo. Cualquier falla (red, estado no 2xx, cuerpo inesperado) lanza `ModelUnavailableError`; un
manejador de FastAPI emite `error` con el tipo y responde `502 {"detail": "model unavailable", "request_id"}`.
Con `MODEL_PROVIDER=gateway`, faltar `CF_ACCOUNT_ID`, `CF_GATEWAY_ID` o `CF_API_TOKEN` impide arrancar; el token
vive en `Settings` con `repr=False` y nunca va al log.

El agente cambia así: `Agent` recibe un modelo o un diccionario de modelos por nombre (`build_models`, ADR 0008)
y `run(..., model_name=...)` usa el modelo elegido en todas las vueltas; `AgentResult` cuenta `cached_calls` y
los tokens cobrables (`billable_input_tokens`, `billable_output_tokens`, que excluyen las llamadas cacheadas); y
`extract_json_object` extrae el primer objeto JSON del texto.

## Consecuencias

- `agent.py` no conoce HTTP ni Cloudflare; cambiar de proveedor sigue siendo una clase nueva y una rama en
  `build_models`, aunque el agente sí cambió para admitir varios modelos, caché y JSON imperfecto.
- `ModelReply` agrega `cached` con valor `False` por omisión: los modelos existentes no cambian.
- El `500` queda para errores propios; el `502` dice a soporte que falló el proveedor.
- El modelo real puede devolver JSON imperfecto: el agente extrae el primer objeto JSON del texto.
