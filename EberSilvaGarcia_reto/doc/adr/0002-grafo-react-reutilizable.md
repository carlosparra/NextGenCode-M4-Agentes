# 0002. Un grafo ReAct reutilizable con topes y autocorrección

- Estado: aceptada
- Fecha: 2026-11-24

## Contexto

El supervisor y el agente de vacaciones siguen el mismo ciclo: pensar, actuar, observar.
Los modelos pequeños (Llama 3.1 8B) a veces piden herramientas que no existen, mandan
argumentos mal formados o contestan sin consultar.

## Decisión

`app/agents/react.py` define `ReactAgent`, un `StateGraph` con los nodos `reason`, `act`
y `give_up`:

- **Tope de pasos** por agente (`AGENT_MAX_STEPS`, `SUBAGENT_MAX_STEPS`) y
  `recursion_limit` de LangGraph como segunda red.
- **Cada argumento se valida** con un esquema Pydantic antes de ejecutar. Un error se
  devuelve al modelo como observación y queda auditado (`tool_rejected`), no truena.
- **Autocorrección con tope**: si una regla de código dice que la pregunta exige una
  herramienta (menciona `EMP-####` o un área) y el modelo contesta sin usarla, se le
  recuerda una sola vez (`agent_self_correction`).
- **`return_direct`** por herramienta (ver ADR 0004).
- El protocolo es JSON con `thought`: el razonamiento queda visible en la respuesta, en
  MCP y en LangSmith.

## Consecuencias

- Un agente nuevo se arma con una lista de `Tool` y un prompt.
- Con el modelo real, la combinación de ejemplos en el prompt, validación y autocorrección
  llevó los errores de formato de 2/5 a 0/5 (ver `doc/costs.md`).
