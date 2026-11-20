# 0003. Un solo agente con bucle con tope y protocolo JSON

## Contexto

El agente debe decidir entre usar herramientas o responder, sin quedar en un bucle infinito ni depender de
un formato libre del modelo.

## Decisión

Un único agente con dos herramientas de solo lectura (`get_employee`, `search_by_department`). El modelo
responde siempre un objeto JSON: `{"tool", "args"}` o `{"answer"}`. El resultado de la herramienta vuelve como
mensaje `user` con el prefijo `Resultado de la herramienta: `. El bucle corre como máximo `AGENT_MAX_STEPS`
vueltas; si se agota, responde exactamente `No pude completar la respuesta. Intenta con una pregunta más concreta.`
JSON inválido o herramienta desconocida se devuelven al modelo como resultado de error, sin lanzar excepciones.

## Consecuencias

- El costo y la latencia por pregunta tienen un límite conocido.
- Con `AGENT_MAX_STEPS=1` una pregunta que necesita herramienta siempre llega al tope; el valor por omisión es 3.
- Agregar herramientas es registrar una función más en el agente; varios agentes quedan fuera de esta sesión.
