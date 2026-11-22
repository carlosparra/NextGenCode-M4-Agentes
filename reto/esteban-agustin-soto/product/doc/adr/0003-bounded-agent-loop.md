# 0003. Bucle del agente con tope

## Contexto
Un modelo podría pedir herramientas sin parar, con costo y latencia sin límite.

## Decisión
El agente da como máximo `AGENT_MAX_STEPS` vueltas (3 por omisión). Si no hay respuesta, devuelve el mensaje fijo `No pude completar la respuesta. Intenta con una pregunta más concreta.`. Las salidas inválidas del modelo cuentan como vuelta.

## Consecuencias
- El costo y el tiempo por petición tienen un máximo conocido.
- Preguntas que requieran más vueltas fallan con un mensaje claro y se resuelven subiendo el tope.
- Nunca hay un error 500 por un bucle infinito.
