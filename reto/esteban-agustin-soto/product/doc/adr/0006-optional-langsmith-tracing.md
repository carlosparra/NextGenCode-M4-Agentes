# 0006. Trazas de LangSmith opcionales y privadas por omisión

## Contexto
Las trazas ayudan a depurar al agente, pero mandan datos a un tercero y el producto debe funcionar sin red ni clave.

## Decisión
Un módulo `tracing.py` envuelve `@traceable`. Solo se activa con `LANGSMITH_TRACING=true` y `LANGSMITH_API_KEY`; si no, devuelve la función original y no se conecta. Corrida del agente, llamada al modelo y herramientas son trazas con el `request_id` en los metadatos. `HIDE_INPUTS` y `HIDE_OUTPUTS` valen `true` por omisión. La clave se lee del entorno y nunca va al log ni al código.

## Consecuencias
- Sin clave el producto es idéntico y las pruebas no necesitan red.
- Ver texto en LangSmith exige poner `HIDE_*` en `false` de forma explícita.
- El `request_id` une el log con la traza.
- Se agrega `langsmith` a `requirements.txt` y el agente y el modelo dependen de la envoltura, no de la librería.
