# 0003. Un solo agente con bucle de herramientas con tope

Estado: propuesto

## Contexto

El agente alterna entre pedir herramientas y responder. Sin límite, un modelo confundido podría llamar
herramientas para siempre, con costo y latencia sin control. El contrato además espera conteos exactos de pasos.

## Decisión

Un solo agente con dos herramientas de solo lectura (`get_employee`, `search_by_department`) en un registro
nombre a función. Un paso es una llamada al modelo. En cada paso: si el modelo responde, se termina; si pide una
herramienta, se ejecuta, se anota en `tools_used` y su resultado se agrega como mensaje `user` que empieza con
`Resultado de la herramienta: `. Los errores (JSON inválido, herramienta desconocida, argumentos malos) se
devuelven al modelo como resultado y consumen el paso. Al llegar a `AGENT_MAX_STEPS` sin respuesta se devuelve
exactamente `No pude completar la respuesta. Intenta con una pregunta más concreta.`

## Consecuencias

- Costo y tiempo por pregunta acotados; con el tope por omisión (3) cabe una herramienta y una respuesta.
- Preguntas que necesiten varias herramientas pueden caer en la respuesta de respaldo; se ajusta el tope por
  configuración.
- Agregar herramientas es sumar entradas al registro, sin cambiar el bucle.
