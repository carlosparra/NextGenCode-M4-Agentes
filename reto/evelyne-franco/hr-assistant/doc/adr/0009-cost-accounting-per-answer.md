# ADR 0009: Costo calculado por llamada con una tabla de precios local

## Contexto

Cada palanca de costo (enrutamiento, ventana de historial, tope de salida, caché) debe medirse, y se abandona si
baja la calidad. Para medir sin red hace falta que el modelo simulado también tenga precio. Los costos por
pregunta son de millonésimas de dólar.

## Decisión

- `pricing.py` carga `data/model_prices.json` (USD por millón de tokens) al arrancar. Si faltan los precios de
  `MODEL_SMALL` o `MODEL_LARGE`, el producto no arranca.
- El agente calcula el costo por llamada: `input * precio_in + output * precio_out` dividido entre un millón.
  Una llamada con `cf-aig-cache-status: HIT` cuenta en `cached_calls` y cuesta 0.
- El costo no se redondea al calcular ni al responder.
- Con `MODEL_PROVIDER=fake` existen dos modelos simulados con los nombres de `MODEL_SMALL` y `MODEL_LARGE`: responden
  igual, pero cuestan según su nombre.
- La ventana de historial recorta solo el historial del cliente; nunca la pregunta ni los resultados de
  herramientas de la corrida.
- `/metrics` suma `cost_usd` por proceso, igual que los tokens (ADR 0005).

## Consecuencias

- `verification evaluate` compara línea base y palancas sin red y de forma repetible.
- Los precios cambian: hay que actualizar la copia en `data/` cuando cambie `spec/model_prices.json`.
- El costo es una estimación del producto; la factura real de Cloudflare puede diferir por redondeos o tokens
  que el gateway cuente distinto.
