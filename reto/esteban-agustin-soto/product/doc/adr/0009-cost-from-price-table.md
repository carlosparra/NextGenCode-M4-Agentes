# 0009. Costo calculado en la app con una tabla de precios

## Contexto
El costo por respuesta debe poder medirse sin red y sin gastar cuota, y los precios cambian con el tiempo. La evaluación necesita que el modelo simulado también tenga precio.

## Decisión
`pricing.py` lee `data/model_prices.json` (USD por millón de tokens) y calcula el costo por llamada con los tokens de entrada y salida y el nombre del modelo. Una llamada con `cached=true` cuesta 0. Los dos modelos simulados se llaman como `MODEL_SMALL` y `MODEL_LARGE` y se costean con el precio de ese nombre. Un modelo sin precio da un error claro. `/ask` devuelve `cost_usd` y `/metrics` lo acumula por proceso.

## Consecuencias
- Las palancas se miden de forma repetible en `verification evaluate`.
- Los precios son datos revisables, con fecha, y no están en el código.
- El costo es una estimación con la tabla local, no la factura de Cloudflare.
- Cambiar de modelo exige agregar su precio.
