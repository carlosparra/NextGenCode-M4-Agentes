# ADR 0006: Contenedor con compuerta de pruebas y despliegue en Render

## Contexto

La entrega vive en una subcarpeta de un fork. GitHub solo ejecuta workflows que están
en la raíz del repositorio, y la raíz no se debe modificar.

## Decisión

- El `Dockerfile` tiene una etapa `test` que corre las pruebas y pylint; la etapa
  final depende de ella, así que una imagen solo existe si las pruebas pasaron.
- `render.yaml` usa `autoDeployTrigger: commit`, porque con `checksPass` y sin CI
  activo Render nunca publicaría.
- El workflow de CI queda dentro de la carpeta como referencia.

## Consecuencias

- La compuerta corre en cada construcción, en Render y en cualquier máquina.
- Las pruebas de navegador no están en la compuerta; se corren con
  `scripts/run_e2e.py` antes de publicar.
