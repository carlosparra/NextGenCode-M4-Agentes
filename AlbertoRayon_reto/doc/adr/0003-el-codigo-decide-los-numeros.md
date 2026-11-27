# ADR 0003: El código decide los números

## Contexto

Un modelo de lenguaje puede inventar un saldo de vacaciones o una cifra de un resumen
con total seguridad. En Recursos Humanos un número inventado es un problema real.

## Decisión

- El saldo se calcula en `app/vacations.py` con la tabla del artículo 76 de la LFT.
- La herramienta `get_vacation_balance` es de respuesta directa: su resultado es la
  respuesta final y el modelo no la reescribe.
- En la herramienta MCP `vacation_balance`, si la respuesta del modelo no es el
  cálculo, se entrega el valor verificado y el razonamiento lo dice.
- En los resúmenes, el crítico rechaza cualquier cifra que no esté en los hechos; si
  tras dos revisiones no pasa, se entregan los hechos verificados.

## Consecuencias

- Las cifras son reproducibles y tienen pruebas unitarias.
- Las respuestas de vacaciones son menos conversacionales, a cambio de ser exactas.
