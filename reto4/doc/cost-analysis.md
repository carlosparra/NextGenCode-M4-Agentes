# Análisis de costos

## Estrategias aplicadas

Las cuatro palancas se configuran con variables de entorno y se explican en el ADR 0007:

| Palanca | Variable | Qué hace | Trade-off |
| --- | --- | --- | --- |
| Enrutamiento de modelo | `ROUTING`, `ROUTER_MAX_CHARS`, `MODEL_SMALL`, `MODEL_LARGE` | Manda las preguntas simples a `llama-3.1-8b-instruct-fast` y las largas o con palabras clave a `llama-3.3-70b-instruct-fp8-fast` | La regla es explicable y no cuesta, pero no entiende el significado: una pregunta compleja sin palabra clave va al modelo pequeño |
| Ventana de historial | `HISTORY_WINDOW` | Solo manda al modelo los últimos mensajes de la conversación | Menos tokens de entrada, pero se pierde el contexto de mensajes viejos |
| Tope de salida | `MODEL_MAX_TOKENS=300`, `MODEL_TEMPERATURE=0` | Limita cuánto escribe el modelo y lo hace determinista | Una respuesta muy larga se corta |
| Caché del gateway | `CACHE_TTL_SECONDS` | Cloudflare AI Gateway regresa la misma respuesta sin volver a cobrarla; una llamada cacheada cuesta 0 | Puede servir datos viejos durante el TTL; viene apagada por omisión |

El costo de cada petición se calcula con [`data/model_prices.json`](../hr-assistant/data/model_prices.json)
(USD por millón de tokens de entrada y de salida). Se regresa en `cost_usd` de cada respuesta, se suma en
`/metrics` y se registra en el evento `agent_run` del log.

## Evidencia frente a la línea base

`uv run python -m verification evaluate` corre el mismo conjunto de preguntas dos veces:

- **Línea base:** `ROUTING=false`, que siempre usa el modelo grande, y `HISTORY_WINDOW=1000`, que manda todo el
  historial.
- **Palancas:** la configuración por omisión.

Resultado del 2026-11-19:

| Configuración | Calidad | Costo total (USD) | Tokens de entrada |
| --- | --- | --- | --- |
| Línea base | 100 % | 0.000852 | 1655 |
| Palancas | 100 % | 0.000111 | 1085 |
| **Ahorro** | sin pérdida | **-87 %** | **-34 %** |

Por ejemplo, una pregunta simple con la herramienta `search_by_department` cuesta USD 0.0000236 con el modelo
pequeño. El mismo trabajo con el modelo grande cuesta cerca de 6 veces más, según la tabla de precios: USD 0.293 contra 0.045 por millón de tokens de entrada, y
2.253 contra 0.384 por millón de tokens de salida.

## Limitaciones de la medición

- La evaluación usa el modelo simulado, que es determinista y no cuesta. Por eso la calidad sale igual en las dos
  configuraciones por construcción. El ahorro sí es real, porque sale de los precios publicados de Workers AI y
  de los tokens contados.
- Como siguiente paso, la misma evaluación puede correrse con `MODEL_PROVIDER=gateway` para medir la calidad
  real del modelo pequeño frente al grande.
