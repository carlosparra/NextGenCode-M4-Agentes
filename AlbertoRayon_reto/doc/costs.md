# Costos

Regla del módulo: una palanca se mide o no se usa. Si baja la calidad, no entra.

## Línea base

Todo al modelo grande (`ROUTING=false`), historial completo, prompt largo y sin
cachés. Es la configuración más simple de construir y la más cara.

## Palancas

| Palanca | Variable | Qué hace | Trade-off |
| --- | --- | --- | --- |
| Enrutamiento | `ROUTING`, `ROUTER_MAX_CHARS` | Las preguntas simples van al modelo chico; las largas o con «compara», «resume», «explica», «por qué», «analiza» o «todos», al grande | El modelo chico sigue peor las instrucciones; se compensa con el ejemplo en el prompt y la verificación en código |
| Ventana de historial | `HISTORY_WINDOW` | Solo viajan los últimos mensajes | El agente olvida lo anterior a la ventana |
| Prompt compacto | `COMPACT_PROMPT` | Prompt de sistema corto, con un solo ejemplo | Menos guía para el modelo |
| Tope de salida | `MODEL_MAX_TOKENS` | Limita los tokens de cada respuesta | Una respuesta larga puede cortarse |
| Caché de AI Gateway | `CACHE_TTL_SECONDS` | Una llamada idéntica al modelo no se cobra | Respuesta vieja durante el TTL |
| Caché de respuestas | `RESPONSE_CACHE_TTL_SECONDS` | Una pregunta idéntica no llama al modelo | Respuesta vieja durante el TTL; vive en la memoria del proceso |

Además, dos decisiones de diseño que ahorran sin ser palancas configurables: el
supervisor y el enrutador son reglas en código (cero tokens), y la herramienta de
vacaciones responde directo, sin una segunda llamada al modelo.

## Cómo se mide

`scripts/evaluate.py` corre `data/eval_set.json` (15 casos: directorio, vacaciones,
resúmenes y una pregunta fuera de tema) con cada configuración. Cada pregunta lleva
un historial de relleno de 10 mensajes y el set se corre dos veces, para que las
cachés tengan algo que ahorrar. Mide calidad (la respuesta contiene lo esperado),
costo, tokens y latencia, y termina con error si las palancas bajan la calidad o no
bajan el costo.

```bash
python scripts/evaluate.py                     # modelo simulado
python scripts/evaluate.py --provider gateway  # modelo real
```

## Resultados con el modelo simulado

El modelo simulado es determinista y cobra con el precio del modelo que se le pide,
así que la medición es repetible y no gasta cuota. Salida real en
[`../evidence/costs-fake.md`](../evidence/costs-fake.md):

| Configuración | Calidad | Costo USD | Ahorro |
| --- | ---: | ---: | ---: |
| Línea base (sin palancas) | 100 % | 0.005527 | 0.0 % |
| + enrutamiento | 100 % | 0.001544 | 72.1 % |
| + ventana de historial | 100 % | 0.005104 | 7.7 % |
| + prompt compacto | 100 % | 0.004725 | 14.5 % |
| Palancas sin cachés | 100 % | 0.001356 | 75.5 % |
| Todas + caché de respuestas | 100 % | 0.000678 | 87.7 % |

Lectura:

- El enrutamiento es la palanca que más pesa: el modelo grande cuesta 6.5 veces más
  por token de entrada y 5.9 veces más por token de salida.
- El ahorro se reporta **sin cachés (75.5 %)** y aparte **con caché (87.7 %)**. El
  segundo número depende de cuánto se repitan las preguntas: aquí el set se corre
  dos veces, así que la mitad de las preguntas son repetidas.
- El tope de salida no se nota con el modelo simulado, porque sus respuestas son
  cortas; es una protección contra respuestas largas del modelo real.

## Resultados con el modelo real

Pendiente de medir con las credenciales de Cloudflare del alumno. Al correr
`python scripts/evaluate.py --provider gateway --output evidence/costs-gateway.md`
la tabla queda en `evidence/costs-gateway.md`, incluida la fila de la caché del
gateway.

Con el modelo real la calidad sí puede variar entre el modelo chico y el grande; por
eso la evaluación compara calidad además de costo.

## Costo en vivo

- Cada respuesta de `/ask` trae `model`, `route`, `cached_calls` y `cost_usd`.
- `/metrics` acumula `cost_usd`, `baseline_cost_usd` y `savings_pct`.
- Los precios están en `data/model_prices.json`, con su fuente y la fecha en que se
  revisaron. Hay que revisarlos antes de reportar costos reales: cambian.
