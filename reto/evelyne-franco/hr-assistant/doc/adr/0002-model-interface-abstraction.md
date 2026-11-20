# ADR 0002: Abstraccion del modelo mediante interfaz

## Contexto

El sistema necesita un modelo de lenguaje para interpretar preguntas y decidir
que herramientas usar. En esta sesion solo existe un modelo simulado (fake), pero
en sesiones futuras se usaran modelos reales. Necesitamos que el agente no
dependa de un proveedor concreto.

## Decision

Se define una interfaz `complete(messages)` en `llm.py` que todo proveedor de
modelo debe implementar. El agente solo conoce esta interfaz. La variable de
entorno `MODEL_PROVIDER` determina que implementacion se instancia. En esta
sesion solo se soporta el valor `fake`.

## Consecuencias

- Anadir un proveedor real (OpenAI, Anthropic, etc.) solo requiere una nueva
  clase que implemente `complete(messages)` y registrarla en la fabrica.
- El modelo simulado es determinista, sin red ni costo, lo que permite pruebas
  rapidas y reproducibles.
- El agente se prueba unitariamente con el modelo simulado sin necesidad de
  mocks adicionales.
