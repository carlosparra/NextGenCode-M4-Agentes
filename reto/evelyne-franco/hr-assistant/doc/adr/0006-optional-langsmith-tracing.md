# ADR 0006: Trazas de LangSmith opcionales y privadas por omisión

## Contexto

Las trazas muestran cada vuelta del agente, cada llamada al modelo y cada
herramienta, pero dependen de un servicio externo y pueden sacar datos personales
fuera de la empresa. El producto debe funcionar sin él.

## Decisión

- `tracing.py` expone un decorador `traceable` propio. Si `LANGSMITH_TRACING=true`
  y existe `LANGSMITH_API_KEY`, delega en `langsmith.traceable`; si no, no hace
  nada y no importa ni conecta con LangSmith.
- Se trazan `Agent.run`, cada `complete` del modelo y cada herramienta, con el
  `request_id` en los metadatos.
- `HIDE_INPUTS` y `HIDE_OUTPUTS` valen `true` por omisión y se traducen a las
  variables de LangSmith para ocultar entradas y salidas.
- La clave solo se lee del entorno; nunca se guarda en `Settings` ni se registra.

## Consecuencias

- Sin clave, el producto y sus pruebas no tocan la red.
- El código del agente no depende de LangSmith: cambiar de proveedor de trazas
  solo toca `tracing.py`.
- Con los valores por omisión las trazas muestran estructura y tiempos, no
  contenido; quien quiera ver texto debe cambiarlo de forma explícita.
