# 0011. Compliance como código al arrancar y publicación solo con CI verde

## Contexto

Una configuración insegura en producción (modelo simulado, claves cortas, trazas que mandan textos) no rompe
ninguna prueba y pasaría inadvertida. Además, Render publicaría cualquier push aunque las pruebas fallen.

## Decisión

- `compliance.py` expone `check_production(config)`, que devuelve la lista de reglas incumplidas: `MODEL_PROVIDER`
  es `fake`; `API_KEYS` vacía o con una clave de menos de 16 caracteres (se nombra el cliente y el largo, nunca la
  clave); `LANGSMITH_TRACING=true` con `HIDE_INPUTS` o `HIDE_OUTPUTS` distintos de `true`.
- `load_config` la llama cuando `ENVIRONMENT=production` y lanza un solo `ConfigError` con todas las reglas
  incumplidas. Así el proceso no arranca (ADR 0004). `ENVIRONMENT` solo admite `development` o `production`.
- `doc/compliance-checklist.md` lista cada regla, la función que la aplica y la prueba que la comprueba.
- El producto se empaqueta con `Dockerfile` (`python:3.12-slim`, usuario no root). El CI de GitHub Actions encadena
  `style`, `unit`, `e2e` y `docker` con `needs`, y `render.yaml` usa `autoDeployTrigger: checksPass`.

## Consecuencias

- Una mala configuración en Render se ve como un despliegue fallido con un mensaje claro, no como un servicio
  inseguro en línea.
- Desarrollo y CI siguen usando el modelo simulado sin tocar estas reglas.
- Si se agrega una regla, se agrega en `compliance.py`, en su prueba y en la tabla del checklist.
- Ningún secreto vive en el repositorio: en `render.yaml` van con `sync: false` y en el CI la clave es de prueba.
