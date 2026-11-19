# 0009. Costo por respuesta, ventana de historial y caché del gateway

Estado: propuesto

## Contexto

Cada palanca de costo debe medirse: si baja la calidad, no se usa. Para medir hace falta un costo por respuesta
calculado igual con el modelo real y con el simulado, sin red.

## Decisión

- Precios en `data/model_prices.json` (USD por millón de tokens), ruta en `PRICES_PATH`. Al arrancar se exige
  que `MODEL_SMALL` y `MODEL_LARGE` tengan precio.
- El agente suma por llamada `(entrada * precio_entrada + salida * precio_salida) / 1e6` con el nombre del
  modelo enrutado. Una llamada con `cf-aig-cache-status: HIT` cuenta en `cached_calls` y cuesta 0.
- `POST /ask` agrega `model`, `route`, `cached_calls` y `cost_usd`; `/metrics` agrega `cost_usd` acumulado
  (por proceso, como el ADR 0005). Excepción con modelo inyectado: ADR 0010.
- La página muestra modelo y costo de cada respuesta con `textContent`, redondeado solo al mostrar.
- Solo se mandan al modelo los últimos `HISTORY_WINDOW` mensajes del historial del cliente; nunca se recortan
  la pregunta ni los resultados de herramientas. `MODEL_MAX_TOKENS` va en cada llamada.
- La caché va apagada por omisión (`CACHE_TTL_SECONDS=0`) porque guarda respuestas con datos personales.

## Consecuencias

- `verification evaluate` compara línea base y palancas con el modelo simulado y decide con datos (primera
  medición: misma calidad, costo 86 % menor).
- Cambiar precios no requiere tocar código; precios viejos dan costos equivocados, no fallos.
- Una ventana corta puede perder contexto en conversaciones largas; se ajusta con `HISTORY_WINDOW` y se mide.
