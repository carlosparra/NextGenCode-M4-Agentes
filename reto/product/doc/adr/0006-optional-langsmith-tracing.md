# 0006. Trazas de LangSmith opcionales detrás de un adaptador

Estado: aceptado; reemplazado en parte por 0017.

> Nota de vigencia: el adaptador descrito aquí sigue vigente. Lo que cambió es la obligatoriedad: desde
> `spec/05-reto.md` las trazas son obligatorias en Render (`render.yaml` fija `LANGSMITH_TRACING=true` y declara
> `LANGSMITH_API_KEY` con `sync: false`). En local, en las pruebas y en el CI siguen siendo opcionales. Ver ADR 0017.

## Contexto

Las trazas por corrida, por llamada al modelo y por herramienta ayudan a depurar al agente, pero envían datos
a un servicio externo. El producto debe funcionar igual sin clave y no filtrar preguntas ni respuestas.

## Decisión

- `tracing.py` expone `build_tracer(settings)`: devuelve un trazador con `@traceable` solo si
  `LANGSMITH_TRACING=true` y existe `LANGSMITH_API_KEY`; en cualquier otro caso, un `NoopTracer`.
- `langsmith` se importa de forma perezosa dentro del trazador real; sin clave no se importa ni se conecta.
- `HIDE_INPUTS` y `HIDE_OUTPUTS` valen `true` por omisión y se aplican al cliente de LangSmith.
- El `request_id` va en los metadatos de cada traza. La clave la lee el SDK del entorno; nunca se guarda en
  `Settings` ni se escribe en el log.
- Un fallo del trazador se captura y no afecta la respuesta.

## Consecuencias

- El agente depende de una interfaz pequeña, no de LangSmith; las pruebas usan un trazador falso sin red.
- Con los valores por omisión, las trazas muestran estructura y tiempos, no contenido.
- Se agrega `langsmith` a `requirements.txt` aunque no siempre se use.
