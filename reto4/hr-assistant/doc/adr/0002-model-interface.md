# 0002. Modelo detrás de la interfaz complete(messages)

## Contexto

Hoy solo existe un modelo simulado, pero más adelante se usará un modelo real. El agente no debe cambiar
cuando cambie el proveedor, y las pruebas deben correr sin red ni costo.

## Decisión

`llm.py` define un protocolo con un único método `complete(messages)` que devuelve el texto JSON del modelo
y sus tokens de entrada y salida. `FakeModel` lo implementa con reglas deterministas. Una fábrica elige la
implementación según `MODEL_PROVIDER`; `create_app()` recibe el modelo ya construido.

## Consecuencias

- Agregar un proveedor es una clase nueva y una rama en la fábrica, sin tocar `agent.py`.
- Las pruebas inyectan modelos de prueba (por ejemplo, uno que siempre pide herramienta para probar el tope).
- `FakeModel` necesita conocer los departamentos; se le pasan desde el directorio al construirlo.
