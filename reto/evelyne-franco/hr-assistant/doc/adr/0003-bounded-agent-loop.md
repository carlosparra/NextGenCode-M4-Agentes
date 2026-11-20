# ADR 0003: Bucle del agente con tope de pasos

## Contexto

El agente ejecuta un bucle en el que el modelo puede pedir herramientas
sucesivamente antes de dar una respuesta final. Si el modelo nunca responde con
`answer`, el bucle seria infinito, bloqueando el servidor y consumiendo recursos.

## Decision

El bucle del agente tiene un tope configurable (`AGENT_MAX_STEPS`, por omision 3).
Si se alcanza el tope sin obtener una respuesta del modelo, el agente devuelve un
mensaje de fallback fijo: "No pude completar la respuesta. Intenta con una
pregunta mas concreta."

## Consecuencias

- Se garantiza que toda peticion termina en tiempo acotado, independientemente
  del comportamiento del modelo.
- Un valor muy bajo (por ejemplo 1) puede impedir que el agente complete
  consultas que requieren herramientas; esto se mitiga con el valor por
  omision de 3.
- Valores invalidos (0 o negativos) se rechazan al arrancar la aplicacion,
  evitando comportamiento indefinido en ejecucion.
