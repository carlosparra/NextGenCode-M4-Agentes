# ADR 0004: Palancas de costo medidas contra una línea base

## Contexto

Mandar todo al modelo grande, con el historial completo y un prompt largo, es la
opción más simple y la más cara.

## Decisión

Seis palancas, cada una con su variable: enrutamiento de modelo, ventana de historial,
prompt compacto, tope de tokens de salida, caché de AI Gateway y caché de respuestas
del servicio. `scripts/evaluate.py` hace una ablación: mide cada palanca por separado
contra la línea base y falla si baja la calidad.

## Consecuencias

- El ahorro se reporta con y sin cachés, para no inflar el número.
- Las cachés pueden devolver una respuesta vieja durante su TTL; por eso el TTL es
  corto y la caché de respuestas está apagada por omisión.
- El modelo chico sigue peor las instrucciones; lo compensan el ejemplo en el prompt,
  el aviso de corrección y la verificación en código.
