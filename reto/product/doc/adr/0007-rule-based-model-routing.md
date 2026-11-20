# 0007. Enrutamiento por regla entre dos modelos con nombre

Estado: propuesto

## Contexto

Se pide abaratar cada respuesta sin empeorarla. La mayoría de las preguntas (un id, un departamento) no
necesitan el modelo grande. Decidir con otro modelo agregaría costo y latencia, y no sería repetible.
El ADR 0002 fija que el agente solo conoce `complete(messages)`.

## Decisión

- `router.route(question, settings)` es una función pura: `MODEL_LARGE` si `ROUTING=false`, si la pregunta pasa
  de `ROUTER_MAX_CHARS` o si contiene «compara», «resume», «explica», «por qué», «analiza» o «todos» (comparado
  sin mayúsculas ni acentos); si no, `MODEL_SMALL`. Devuelve también el motivo (`route`).
- Se elige una vez por petición; todas las vueltas del bucle usan el mismo modelo.
- `build_models` crea un `LLM` por nombre. Con `fake`, los dos son el mismo modelo simulado con nombres
  distintos, así el costo cambia y la respuesta no.
- El protocolo `complete(messages)` no cambia; el agente recibe el modelo ya elegido.

## Consecuencias

- Determinista, gratis y fácil de probar; `evaluate` lo mide contra la línea base.
- Falsos positivos por subcadena mandan algunas preguntas al modelo caro: cuesta más, no responde peor.
- Cambiar la regla o agregar un tercer modelo toca solo `router.py` y la configuración.
