# Análisis de costo del HR Assistant

Regla de las sesiones 3 y 5: una palanca de costo solo se queda si baja el costo sin bajar la calidad, y eso lo
decide una medición, no una opinión. Decisiones: ADR 0007 (enrutamiento), 0009 (costo por respuesta y palancas 2 a
4) y 0015 (caché de respuestas).

## Cómo se midió

`verification evaluate` levanta el producto tres veces con el modelo simulado (sin red ni cuota; los dos modelos
simulados cuestan según los precios de `data/model_prices.json` para `MODEL_SMALL` y `MODEL_LARGE`). Hace las 8
preguntas de `verification/eval_set.json` dos veces cada una (16 preguntas), todas con un historial de relleno de
10 mensajes, como una conversación larga en un portal donde varias personas preguntan lo mismo.

| Configuración | Qué cambia |
| --- | --- |
| `baseline` | `ROUTING=false` (todo a `MODEL_LARGE`) y `HISTORY_WINDOW=1000` (todo el historial) |
| `levers` | Valores por omisión: `ROUTING=true`, `HISTORY_WINDOW=6`, `MODEL_MAX_TOKENS=300` |
| `cache` | Lo de `levers` más `RESPONSE_CACHE_TTL_SECONDS=300` |

## Resultado

Salida de `verification evaluate`, tal cual:

```
baseline  quality=100% cost_usd=0.002765 input_tokens=6514 ahorro=0%
levers    quality=100% cost_usd=0.000388 input_tokens=5374 ahorro=86%
cache     quality=100% cost_usd=0.000194 input_tokens=2687 ahorro=93%
```

| Configuración | Calidad | Costo total (USD) | Tokens de entrada | Ahorro contra baseline |
| --- | --- | --- | --- | --- |
| baseline | 100 % | 0.002765 | 6514 | 0 % |
| levers | 100 % | 0.000388 | 5374 | 86 % |
| cache | 100 % | 0.000194 | 2687 | 93 % |

Por qué subió contra la medición anterior: el prompt de sistema creció (ahora prohíbe dar datos fuera del
directorio, `doc/security.md`) y viaja en cada llamada al modelo; por eso los tokens de entrada y el costo suben en
las tres configuraciones, mientras los porcentajes de ahorro se mantienen.

Lectura (las cifras derivadas salen de la tabla, no de otra medición):

- Ningún paso pierde calidad y cada uno es más barato que el anterior: `evaluate` pasa.
- De `baseline` a `levers` los tokens de entrada bajan 17.5 % (6514 a 5374), pero el costo baja 86 %: casi todo el
  ahorro viene de pagar el precio del modelo pequeño, no de mandar menos tokens.
- De `levers` a `cache` el costo y los tokens bajan exactamente a la mitad (0.000388 a 0.000194 USD, 5374 a 2687
  tokens): la segunda vuelta de las 8 preguntas sale entera de la caché, con costo 0.
- Por pregunta (total entre 16): baseline 0.000173 USD, levers 0.0000243 USD y cache 0.0000121 USD.
- `evaluate` mide las palancas juntas; no aísla la contribución exacta de cada una.

## Palancas: ahorro y trade-off

| Palanca | Configuración | Ahorro | Trade-off |
| --- | --- | --- | --- |
| 1. Enrutamiento por regla | `ROUTING`, `ROUTER_MAX_CHARS`, `MODEL_SMALL`, `MODEL_LARGE` | La mayor parte del 86 % de `levers`: el costo baja mucho más que los tokens | Una pregunta difícil que no cumpla la regla (corta y sin «compara», «resume», «explica», «por qué», «analiza» o «todos») va al modelo pequeño y puede responder peor; la regla se ajusta y se vuelve a medir |
| 2. Ventana de historial | `HISTORY_WINDOW=6` | Explica la baja de 17.5 % en tokens de entrada de `levers` | En conversaciones largas el modelo pierde el contexto más antiguo; la pregunta y los resultados de herramientas nunca se recortan |
| 3. Tope de salida | `MODEL_MAX_TOKENS=300` | No se nota con el modelo simulado (sus respuestas son cortas); con el modelo real acota el peor caso de cada llamada | Una respuesta larga (por ejemplo, un departamento grande) puede quedar cortada |
| 4. Caché de AI Gateway | `CACHE_TTL_SECONDS=300` (en Render) | No medida en `evaluate`: solo existe con el modelo real; cada llamada con `cf-aig-cache-status: HIT` cuesta 0 y se cuenta en `cached_calls` | Cloudflare guarda hasta 300 s las llamadas al modelo fuera del producto. La pregunta y el historial ya llegan enmascarados (ADR 0014), pero los resultados de herramientas (nombre, puesto, departamento, fecha de ingreso del directorio) sí viajan y quedan en esa caché |
| 5. Caché de respuestas | `RESPONSE_CACHE_TTL_SECONDS=300`, `RESPONSE_CACHE_SIZE=256` | De 86 % a 93 % contra baseline; la mitad del costo de `levers` con cada pregunta repetida una vez | Una respuesta puede quedar vieja hasta 300 s; la caché es por proceso, así que con dos workers hay menos aciertos y se vacía al reiniciar; nunca guarda respuestas con PII ni salidas bloqueadas |

El prompt de sistema es un costo fijo por llamada que ninguna palanca recorta, salvo la caché de respuestas (que
evita la llamada completa). Antes de alargarlo otra vez conviene volver a correr `verification evaluate`.

## Cómo seguir el costo en producción

- Cada respuesta de `/ask` trae `model`, `route`, `cached_calls`, `cost_usd` y, con la caché encendida, `cache`.
- `GET /metrics` da `cost_usd` y `cost_usd_per_request` por proceso, y `cache.hits` y `cache.misses`.
- El log trae `cost_usd` en `request` y en `agent_run`; LangSmith lo trae en los metadatos de `agent_run`.
- El costo se calcula con los precios de `data/model_prices.json`: si Cloudflare cambia precios, el archivo se
  actualiza; precios viejos dan costos equivocados, no fallos.
- Las cifras de esta página son del modelo simulado. Con el modelo real los tokens y los precios cambian; el
  orden de las palancas se espera igual, pero el monto se confirma con `/metrics` en Render.
