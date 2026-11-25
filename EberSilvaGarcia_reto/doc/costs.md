# Optimización de costos

## Cómo se mide

- **Costo por respuesta**: tokens de entrada y salida de cada llamada al modelo por el
  precio de `data/model_prices.json` (USD por millón de tokens, Cloudflare Workers AI). Un
  `HIT` de la caché del gateway cuesta 0. Cada respuesta trae `cost_usd`, `model`,
  `route`, `model_calls` y `cached_calls`, y `/metrics` lleva el acumulado.
- **Calidad**: `scripts/eval_set.json`, 15 preguntas con lo que la respuesta debe
  contener. Son las 8 del curso más 7 nuevas de vacaciones, resúmenes, dato protegido y
  PII en la pregunta.
- **Condiciones**: cada pregunta lleva 10 mensajes de historial (una conversación larga) y
  el set corre **dos veces**, porque en RH las preguntas se repiten.
- **Regla**: una palanca solo se acepta si la calidad no baja.

`python scripts/evaluate.py --fake-only` (CI, sin costo) y `--real` (Cloudflare).

## Palancas

| Palanca | Variable | Qué hace | Trade-off |
| --- | --- | --- | --- |
| Enrutamiento de modelos | `ROUTING`, `ROUTER_MAX_CHARS` | Una regla de código (no otro modelo) manda las preguntas simples al 8B (0.045/0.384 USD por millón) y las complejas («compara», «resume», «analiza», largas) al 70B (0.293/2.253) | El 8B sigue peor el protocolo: hizo falta un prompt con ejemplos, validación y autocorrección (ver hallazgos) |
| Ventana de historial | `HISTORY_WINDOW` | Solo los últimos 6 mensajes llegan al modelo | Se pierde contexto muy antiguo de la conversación |
| Prompts compactos | `COMPACT_PROMPTS` | Prompt de sistema sin relleno y observaciones en JSON compacto | Ninguno medido; la línea base usa prompts «amables» y JSON con sangría |
| Tope de salida | `MODEL_MAX_TOKENS` | 300 tokens máximo por llamada | Respuestas largas se cortan |
| Caché de respuestas | `ANSWER_CACHE_TTL_SECONDS` | Misma pregunta, mismo historial, mismo día y mismo modelo: respuesta guardada por 5 minutos | Una respuesta puede quedar vieja dentro del TTL; por eso la llave incluye la fecha |
| Caché del gateway | `CACHE_TTL_SECONDS` | Cloudflare devuelve la misma llamada sin cobrar | Solo sirve con peticiones idénticas; se apaga con `cf-aig-skip-cache` |
| Hechos por código | (diseño) | Días de vacaciones y hechos del área se calculan sin modelo | Ninguno: además mejora la exactitud |
| `return_direct` | (diseño) | La respuesta verificada de un especialista no vuelve a pasar por el modelo | Menos naturalidad en la redacción |
| Dato protegido sin modelo | (diseño) | «¿Cuál es el CURP de...?» se responde con una política fija: 0 tokens | Ninguno |
| Crítico por código | (diseño) | La reflexión no usa un segundo modelo para criticar | No evalúa estilo, solo hechos |

## Resultados

### Modelo simulado: ablación por palanca

Evidencia en [`evidence/costs/fake.md`](../evidence/costs/fake.md).

| Configuración | Calidad | Tokens entrada | Llamadas | Costo USD | Ahorro |
| --- | ---: | ---: | ---: | ---: | ---: |
| Línea base | 100 % | 18 562 | 72 | 0.008426 | — |
| + enrutamiento | 100 % | 18 562 | 72 | 0.002443 | 71.0 % |
| + ventana de historial | 100 % | 16 890 | 72 | 0.007936 | 5.8 % |
| + prompts compactos | 100 % | 13 888 | 72 | 0.007057 | 16.3 % |
| + caché de respuestas | 100 % | 9 281 | 36 | 0.004213 | 50.0 % |
| **Todas** | **100 %** | **6 108** | **36** | **0.000972** | **88.5 %** |

### Modelo real: Cloudflare Workers AI

9 preguntas representativas × 2 pasadas. Evidencia en
[`evidence/costs/cloudflare.md`](../evidence/costs/cloudflare.md).

| Configuración | Calidad | Tokens entrada | Llamadas | Costo USD | Ahorro | Latencia media |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Línea base | 100 % | 26 855 | 41 | 0.011385 | — | 3.0 s |
| **Palancas de la app** | **100 %** | **10 272** | **19** | **0.001229** | **89.2 %** | **1.3 s** |
| + caché de AI Gateway | 100 % | 8 905 | 19 | 0.000581 | 94.9 % | 0.9 s |

La última fila suma la caché de Cloudflare: en la segunda pasada (preguntas repetidas) las
llamadas idénticas no cuestan. Parte de la caché pudo venir de corridas anteriores; por eso
el ahorro que se reporta como principal es el de la fila anterior, que no depende de ella.

### Verificación del curso

`sesion04/verification evaluate` (su set y su línea base) contra este producto:
calidad 100 % → 100 % y costo de 0.001695 a 0.000245 USD (**−85.5 %**).

## Hallazgos

Medir con el modelo real cambió el diseño. Estos son los hallazgos, en orden:

1. **El 8B no seguía el protocolo**: en 2 de 5 preguntas contestó sin consultar (y una vez
   «inventó» código). Con ejemplos en el prompt (*few-shot*) pasó a 5 de 5, sin costo extra
   que se note.
2. **El enrutamiento bajó la calidad al 89 %**: con todas las palancas, el supervisor (8B)
   reescribió la respuesta verificada de una empleada de baja y dijo «7 días». La caché
   de respuestas repitió el error. **Corrección**: `return_direct` (ADR 0004). La calidad
   volvió a 100 % y se ahorró una llamada por pregunta delegada.
3. **La PII enmascarada confundía al 8B**: con `[EMAIL]` en la pregunta se negaba a
   contestar «¿quién es EMP-0001?». Se resolvió aclarando en el prompt que los marcadores
   son datos ocultos por privacidad, y se agregó una autocorrección con tope como red.
4. **La medición de la caché engañaba**: el gateway guardaba respuestas entre corridas. Las
   configuraciones sin caché ahora mandan `cf-aig-skip-cache` y la tabla separa los casos.

## Lo que no se hizo (y por qué)

- **Un modelo como enrutador o crítico**: cuesta una llamada por decisión; las reglas de
  código bastan y son deterministas.
- **Caché semántica (por similitud)**: con preguntas que cambian un id (`EMP-0001` frente a
  `EMP-0002`) es fácil devolver la respuesta de otro empleado. El riesgo no compensa con
  este volumen.
