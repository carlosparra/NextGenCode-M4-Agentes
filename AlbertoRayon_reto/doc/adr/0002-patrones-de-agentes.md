# ADR 0002: Supervisor en código con especialistas ReAct y de reflexión

## Contexto

Hay tres tipos de pregunta: fichas del directorio, saldo de vacaciones y resúmenes
por departamento. Un solo agente con todas las herramientas es más difícil de probar
y de acotar.

## Decisión

- Un supervisor en LangGraph que delega con una regla en código, no con otro modelo.
- Dos agentes ReAct (directorio y vacaciones) con un protocolo JSON propio
  (`thought`, `tool`, `args` o `answer`) y un ejemplo en el prompt, porque los
  modelos chicos no siguen bien el function calling nativo.
- Un agente de reflexión para resúmenes: el modelo redacta, un crítico en código
  revisa y el modelo corrige, con un máximo de dos revisiones.

## Consecuencias

- La delegación no gasta tokens y es determinista.
- Cada agente tiene pocas herramientas y un tope de pasos.
- Preguntas ambiguas caen en el agente de directorio; ampliar la regla del supervisor
  es un cambio de código con su prueba.
