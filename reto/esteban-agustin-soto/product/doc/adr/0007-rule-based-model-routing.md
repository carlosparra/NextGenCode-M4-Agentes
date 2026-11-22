# 0007. Enrutamiento de modelo con una regla en código

## Contexto
La mayoría de las preguntas de RH son búsquedas simples. Mandarlas todas al modelo grande cuesta unas 6 veces más por token que el pequeño. Usar otro modelo para decidir sumaría costo y latencia a cada pregunta.

## Decisión
`router.py` elige el modelo con una función pura: `MODEL_LARGE` si `ROUTING=false`, si la pregunta pasa de `ROUTER_MAX_CHARS` o si contiene una palabra clave («compara», «resume», «explica», «por qué», «analiza», «todos»); si no, `MODEL_SMALL`. Devuelve también el motivo, que sale como `route`. La ventana de historial y el tope de salida se aplican igual en todos los casos.

## Consecuencias
- La decisión es gratis, determinista y se prueba con una tabla de casos.
- Una pregunta compleja sin palabra clave va al modelo pequeño; el costo es posible calidad menor, que `verification evaluate` vigila.
- Las palancas se miden contra una línea base con `ROUTING=false` y sin ventana.
