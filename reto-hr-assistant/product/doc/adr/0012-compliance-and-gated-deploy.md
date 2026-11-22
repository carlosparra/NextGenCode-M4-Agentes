# 0012. Compliance al arrancar y publicación solo si pasa CI

Estado: propuesto

## Contexto

Una mala configuración en producción (modelo simulado, claves cortas, trazas que mandan preguntas) no debe llegar a
servir tráfico, y ninguna versión debe publicarse sin pasar estilo, pruebas, e2e y la construcción de la imagen.
Las reglas tienen que revisarse solas, no depender de que alguien se acuerde.

## Decisión

`compliance.check(settings)` corre dentro de `create_app` después de `load_settings`. Con `ENVIRONMENT=production`
lanza `ConfigError` si `MODEL_PROVIDER=fake`, si `API_KEYS` está vacía o alguna clave tiene menos de 16 caracteres,
o si `LANGSMITH_TRACING=true` y `HIDE_INPUTS` o `HIDE_OUTPUTS` no son `true`. `doc/compliance-checklist.md` enlaza
cada regla con su código y su prueba. La imagen es `python:3.12-slim` con usuario sin privilegios. El CI encadena
`style` -> `unit` -> `e2e` -> `docker` con `needs`, y `render.yaml` usa `autoDeployTrigger: checksPass` con
`ENVIRONMENT=production` fijo y los secretos con `sync: false`.

## Consecuencias

- Un despliegue mal configurado no levanta, Render no pasa `/health` y conserva la versión anterior.
- En desarrollo no se aplican las reglas: se puede trabajar con `fake` y sin red.
- Agregar una regla es una función y una fila en la checklist, con su prueba.
- El servicio de Render se llama igual que el repositorio para no sobrescribir otro servicio de la cuenta.
- `LANGSMITH_API_KEY` no va en el Blueprint (Render exigiría un valor); se agrega a mano si se encienden las trazas.
