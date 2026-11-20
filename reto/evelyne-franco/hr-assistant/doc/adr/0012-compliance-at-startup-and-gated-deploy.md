# ADR 0012: Compliance al arrancar y publicación condicionada al pipeline

## Contexto

Una configuración insegura en producción, como el modelo simulado, claves débiles o trazas con contenido, no debe
depender de que alguien la revise a mano. Tampoco debe llegar a Render código que no pasó las pruebas.

## Decisión

- `compliance.production_violations(settings)` lista las reglas que fallan con `ENVIRONMENT=production` (fuera de
  producción devuelve una lista vacía):
  - `MODEL_PROVIDER=fake`.
  - `API_KEYS` vacía o con alguna clave de menos de 16 caracteres.
  - `LANGSMITH_TRACING` encendido sin `HIDE_INPUTS` y `HIDE_OUTPUTS` en `true`.
- `create_app()` llama a `compliance.enforce(settings)` antes de construir cualquier otra dependencia. Si hay fallas,
  lanza `ComplianceError` (subclase de `ValueError`), el proceso no arranca y el mensaje nombra las reglas, sin
  valores.
- `doc/compliance-checklist.md` relaciona cada regla con su función y con su prueba.
- El pipeline de CI tiene cuatro trabajos encadenados con `needs`: `style`, `unit`, `e2e` y `docker`. Render usa
  `autoDeployTrigger: checksPass` y publica la imagen Docker solo si el pipeline pasa.
- Los secretos (`API_KEYS`, `CF_ACCOUNT_ID`, `CF_API_TOKEN`) van en Render con `sync: false` y nunca en el
  repositorio.

## Consecuencias

- Una mala configuración en Render se ve como un despliegue fallido en el health check, no como un servicio
  inseguro en línea.
- Las reglas son código con pruebas: agregar una regla es agregar una función, una prueba y una fila al checklist.
- Publicar sigue exigiendo la aprobación de una persona antes de `scripts/publish.py`.
