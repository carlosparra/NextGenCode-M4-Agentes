# 0005. Cloudflare Workers AI a través de AI Gateway autenticado

- Estado: aceptada
- Fecha: 2026-11-24

## Contexto

El curso usa Cloudflare Workers AI (plan gratuito). Se necesitan caché, reintentos, logs
del proveedor y control de gasto sin construirlos a mano.

## Decisión

- Llamar a `.../v1/{cuenta}/{gateway}/workers-ai/v1/chat/completions` (compatible con
  OpenAI) a través del gateway `hr-assistant`.
- Gateway **autenticado**: además del token de Workers AI se manda
  `cf-aig-authorization`. Sin él, conocer el id de la cuenta no basta para usarlo.
- Token con permisos mínimos: Workers AI (Read, Edit) y AI Gateway (Run).
- Caché del gateway por petición (`cf-aig-cache-ttl`); cuando está apagada se manda
  `cf-aig-skip-cache` para medir sin caché de verdad.
- Interfaz `ChatModel` con un modelo simulado de igual contrato, para pruebas, CI y
  evaluación sin costo.

## Consecuencias

- Cambiar de proveedor es escribir otra clase con `complete()`.
- El costo se calcula con `data/model_prices.json`; un `HIT` de caché cuenta como 0.
