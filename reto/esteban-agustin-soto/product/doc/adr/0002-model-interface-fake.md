# 0002. Modelo detrás de una interfaz, con modelo simulado

## Contexto
Más adelante se querrá cambiar de modelo. Hoy se necesitan pruebas deterministas, sin red ni costo.

## Decisión
El agente solo conoce la interfaz `complete(messages)`, que devuelve un objeto JSON (`tool` o `answer`). En esta sesión existe únicamente `FakeModel`, elegido con `MODEL_PROVIDER=fake`.

## Consecuencias
- Cambiar de modelo no toca `agent.py`.
- Las pruebas son reproducibles y gratuitas.
- El comportamiento real de un modelo de lenguaje no se valida todavía.
