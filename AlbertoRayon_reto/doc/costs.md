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
| Caché de AI Gateway | `CACHE_TTL_SECONDS` | Una llamada idéntica al modelo no se cobra | Respuesta vieja durante el TTL; solo con `MODEL_PROVIDER=gateway` |
| Caché de respuestas | `RESPONSE_CACHE_TTL_SECONDS` | Una pregunta idéntica no llama al modelo | Respuesta vieja durante el TTL; vive en la memoria del proceso |

Además, dos decisiones de diseño que ahorran sin ser palancas configurables: el
supervisor y el enrutador son reglas en código (cero tokens), y la herramienta de
vacaciones responde directo, sin una segunda llamada al modelo.

## Cómo se mide

`scripts/evaluate.py` corre `data/eval_set.json` (15 casos: directorio, vacaciones,
resúmenes y una pregunta fuera de tema) con cada configuración. Cada pregunta lleva
un historial de relleno de 10 mensajes. Las configuraciones con caché corren el set
dos veces, para que la caché tenga algo que ahorrar. Mide calidad (la respuesta
contiene lo esperado), costo y tokens promedio por pregunta, y latencia; termina con
error si las palancas bajan la calidad o no bajan el costo.

```bash
python scripts/evaluate.py                     # modelo simulado
python scripts/evaluate.py --provider workers  # modelo real, Workers AI directo
python scripts/evaluate.py --provider gateway  # modelo real, vía AI Gateway
```

## Resultados con el modelo real

Cloudflare Workers AI, medido el 26 de noviembre de 2026. Salida completa en
[`../evidence/costs-workers.md`](../evidence/costs-workers.md):

| Configuración | Calidad | Costo USD por pregunta | Latencia | Ahorro |
| --- | ---: | ---: | ---: | ---: |
| Línea base (sin palancas) | 100 % | 0.00050600 | 2244 ms | 0.0 % |
| + enrutamiento | 93 % | 0.00013984 | 1316 ms | 72.4 % |
| + ventana de historial | 100 % | 0.00046274 | 1955 ms | 8.5 % |
| + prompt compacto | 100 % | 0.00042509 | 1779 ms | 16.0 % |
| Palancas sin cachés | 100 % | 0.00012105 | 907 ms | 76.1 % |
| Todas + caché de respuestas | 93 % | 0.00006013 | 478 ms | 88.1 % |

Lectura:

- **Con todas las palancas y sin cachés: 76.1 % menos costo con la misma calidad
  (100 %)**, y además 60 % menos latencia, porque el modelo chico responde más rápido.
- El enrutamiento es la palanca que más pesa: el modelo grande cuesta 6.5 veces más
  por token de entrada y 5.9 veces más por token de salida.
- Con la caché de respuestas el ahorro sube a 88.1 %. Ese número depende de cuánto
  se repitan las preguntas: aquí el set se corre dos veces, así que la mitad son
  repetidas. Por eso se reporta aparte.
- **Trade-off observado:** en dos corridas el modelo chico falló 1 de 15 casos, la
  pregunta fuera de tema («¿Qué clima hace hoy en Monterrey?»): rechazó la pregunta,
  pero sin la redacción que el caso espera. Después de esta medición se fijó en el
  prompt la respuesta para preguntas fuera de tema; la tabla no se volvió a medir
  para no gastar la cuota diaria gratuita.
- El modelo real no es determinista aunque la temperatura sea 0, así que los números
  varían un poco entre corridas.
- La caché de AI Gateway no está medida: el token actual no tiene permiso de AI
  Gateway (ver `deployment.md`).

## Resultados con el modelo simulado

El modelo simulado es determinista y cobra con el precio del modelo que se le pide:
la medición es repetible y no gasta cuota, así que sirve de compuerta en cada
cambio. Salida en [`../evidence/costs-fake.md`](../evidence/costs-fake.md):

| Configuración | Calidad | Costo USD por pregunta | Ahorro |
| --- | ---: | ---: | ---: |
| Línea base (sin palancas) | 100 % | 0.00020111 | 0.0 % |
| + enrutamiento | 100 % | 0.00005704 | 71.6 % |
| + ventana de historial | 100 % | 0.00018700 | 7.0 % |
| + prompt compacto | 100 % | 0.00017438 | 13.3 % |
| Palancas sin cachés | 100 % | 0.00005077 | 74.8 % |
| Todas + caché de respuestas | 100 % | 0.00002538 | 87.4 % |

El simulado predice bien el ahorro real (74.8 % contra 76.1 %). El tope de salida no
se nota con él, porque sus respuestas son cortas; es una protección contra
respuestas largas del modelo real.

## Costo en vivo

- Cada respuesta de `/ask` trae `model`, `route`, `cached_calls` y `cost_usd`.
- `/metrics` acumula `cost_usd`, `baseline_cost_usd` y `savings_pct`.
- Los precios están en `data/model_prices.json`, con su fuente y la fecha en que se
  revisaron. Hay que revisarlos antes de reportar costos reales: cambian.
