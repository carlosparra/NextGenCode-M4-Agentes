# 0003. Reflection con un crítico determinista

- Estado: aceptada
- Fecha: 2026-11-24

## Contexto

El resumen por área debe ser fiel a los datos. El patrón reflection suele usar un segundo
modelo como crítico, lo que duplica el costo y vuelve no determinista la evaluación.

## Decisión

- `gather_facts` calcula los hechos con código.
- `draft` y `revise` los redacta el modelo.
- `critique` es una función pura (`critique_draft`) con reglas verificables: números
  correctos, nadie de otras áreas, sin PII, largo máximo.
- Tope `REFLECTION_MAX_ROUNDS`; si se agota, una plantilla segura (`fallback`).

## Alternativas consideradas

- **Crítico con modelo**: detecta problemas de tono o claridad, pero cuesta una llamada
  más por vuelta y puede aprobar números incorrectos. Se deja como mejora futura, solo
  para aspectos no verificables por código.

## Consecuencias

- La crítica no cuesta tokens y sus resultados se ven en la respuesta (`critiques`) y en
  MCP, lo que hace visible el razonamiento del agente.
- El modelo simulado entrega a propósito un primer borrador sin la antigüedad promedio,
  para ejercitar el ciclo completo en pruebas y en la demostración.
