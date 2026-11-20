# 0002. Interfaz de modelo, protocolo JSON y bucle con tope

Estado: propuesto

## Contexto

En la sesión 1 solo existía un modelo simulado, pero después se usaría uno real. El agente no debe depender del
proveedor, y un modelo puede pedir herramientas sin fin o responder algo fuera de formato.

## Decisión

- El agente solo conoce el protocolo `LLM` con `complete(messages) -> Completion` (texto y tokens de entrada y
  salida; desde la sesión 3 también `model` y `cached`, en `completion.py`). La fábrica elige la implementación
  según `MODEL_PROVIDER` (`fake` o `gateway`); desde la sesión 3 la API usa `build_models`, que crea un modelo por
  nombre (ADR 0007 y 0008). `build_llm` se conserva para compatibilidad.
- El modelo responde un único objeto JSON: `{"tool", "args"}` o `{"answer"}`. El resultado de una herramienta
  vuelve como mensaje `user` que empieza con `Resultado de la herramienta: `.
- El bucle se detiene en `AGENT_MAX_STEPS` vueltas; si no hay respuesta, devuelve el mensaje fijo de tope.
  Salidas inválidas, herramientas desconocidas o argumentos erróneos se devuelven al modelo como resultado de
  error y consumen una vuelta; nunca producen un 500.

## Consecuencias

- Agregar un proveedor es escribir otra clase y una rama en la fábrica, sin tocar `agent.py` (así entró `gateway`).
- Las pruebas del agente usan modelos dobles deterministas, sin red ni costo.
- El costo y la latencia por pregunta tienen un máximo conocido.
- El protocolo es simple pero frágil con modelos reales; puede requerir un mensaje `system` más estricto.
