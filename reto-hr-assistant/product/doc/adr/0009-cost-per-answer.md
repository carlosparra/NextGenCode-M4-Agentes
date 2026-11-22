# 0009. Costo por respuesta con tabla de precios y palancas medidas

Estado: propuesto

## Contexto

Hay que saber cuánto cuesta cada respuesta y demostrar que las palancas (enrutamiento, ventana de historial, tope
de salida y caché) bajan el costo sin bajar la calidad. Los precios cambian y no deben vivir en el código.

## Decisión

`pricing.PriceTable` carga `PRICES_PATH` (copia de `spec/model_prices.json`, USD por millón de tokens); si
`MODEL_SMALL` o `MODEL_LARGE` no tienen precio, la aplicación no arranca. El agente cuenta, además de los tokens
totales, los tokens cobrables (los de llamadas que no fueron `HIT` de caché) y `cached_calls`; `main.py` calcula
`cost_usd` con el modelo elegido y esos tokens. La API devuelve `model`, `route`, `cached_calls` y `cost_usd`;
`/metrics` acumula `cost_usd`. Solo se mandan los últimos `HISTORY_WINDOW` mensajes (0 manda ninguno), cada
llamada lleva `MODEL_MAX_TOKENS` y, con `CACHE_TTL_SECONDS > 0`, el encabezado `cf-aig-cache-ttl`.

## Consecuencias

- Con `fake` el costo es real en forma (precio por nombre) y aproximado en tokens (palabras): sirve para
  comparar configuraciones, no para facturar.
- `verification evaluate` decide con código: misma calidad o mejor y menos costo que la línea base.
- Una ventana muy corta puede perder contexto con el modelo real; se ajusta con datos, no por intuición.
- Actualizar precios es cambiar un archivo JSON, sin tocar código.
