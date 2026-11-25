# 0008. Render con Docker y compuerta de calidad dentro de la imagen

- Estado: aceptada
- Fecha: 2026-11-24

## Contexto

El reto se entrega en una carpeta de un fork. GitHub Actions solo ejecuta flujos de la
raíz del repositorio y el reto pide no tocar nada fuera de la carpeta.

## Decisión

- `Dockerfile` de dos etapas: `test` corre pytest (cobertura 80 % o más) y pylint 10/10;
  `runtime` copia un archivo que solo existe si `test` terminó bien. Si las pruebas
  fallan, no hay imagen y Render no publica.
- Imagen mínima `python:3.12-slim`, usuario sin root (uid 10001), código de solo lectura
  para el proceso, `HEALTHCHECK` y `preflight` antes de uvicorn.
- `render.yaml` con `rootDir: EberSilvaGarcia_reto`, plan gratuito, `healthCheckPath`,
  secretos con `sync: false` y `autoDeployTrigger: commit`: con `checksPass` Render
  esperaba checks de GitHub que el fork no ejecuta y no publicaba (se comprobó en vivo).
- `.github/workflows/ci.yml` queda dentro de la carpeta (style → unit → e2e → security →
  docker) y se activa copiándolo a la raíz del fork.

## Consecuencias

- La compuerta de calidad funciona aunque el CI de GitHub no corra.
- La construcción en Render tarda más (instala las dependencias de prueba en la primera
  etapa), a cambio de no publicar nunca código que no pasa.
