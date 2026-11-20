# 0013. Compliance como código al arrancar y publicación solo si el CI pasa

Estado: aceptado

> Nota de vigencia: la última consecuencia (`LANGSMITH_API_KEY` fuera del Blueprint) quedó reemplazada por el
> ADR 0017: `render.yaml` ahora declara `LANGSMITH_API_KEY` con `sync: false` y fija `LANGSMITH_TRACING=true`.

## Contexto

En producción no puede correr el modelo simulado, ni faltar claves o ser cortas, ni mandarse entradas o salidas a
LangSmith. Además, nada debe llegar a Render sin pasar estilo, pruebas, e2e y la construcción de la imagen.

## Decisión

- `compliance.enforce(settings)` corre en `create_app` (con configuración del entorno o inyectada). Con
  `ENVIRONMENT=production` lanza `ConfigError` si `MODEL_PROVIDER=fake`, si `API_KEYS` está vacía o alguna clave
  tiene menos de 16 caracteres, o si `LANGSMITH_TRACING=true` y `HIDE_INPUTS` o `HIDE_OUTPUTS` no valen `true`. El
  mensaje nombra la regla, nunca el valor.
- `doc/compliance-checklist.md` enlaza cada regla con su código y su prueba.
- El producto se empaqueta en `python:3.12-slim` con un usuario que no es root. El CI (`style -> unit -> e2e ->
  docker`, encadenado con `needs`) corre en cada push y pull request.
- `render.yaml` usa `runtime: docker`, `autoDeployTrigger: checksPass`, valores de producción fijos en el archivo y
  los secretos con `sync: false`. El servicio se llama como el repositorio.

## Consecuencias

- Una configuración insegura falla al desplegar, en el health check de Render, y no sirve tráfico.
- Las reglas tienen pruebas: cambiarlas sin actualizar la tabla y las pruebas deja el CI en rojo.
- Render publica solo commits con el CI en verde. Un CI roto bloquea también los arreglos urgentes.
- (Reemplazado por ADR 0017) `LANGSMITH_API_KEY` no va en el Blueprint; se agrega a mano en Render si se encienden
  las trazas.
