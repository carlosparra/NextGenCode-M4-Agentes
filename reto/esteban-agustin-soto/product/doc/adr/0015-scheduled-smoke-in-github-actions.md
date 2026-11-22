# 0015. Prueba de humo programada en GitHub Actions

## Contexto
La prueba de humo contra el servicio publicado se corría a mano y `scripts/smoke.py` tenía solo tres comprobaciones, mientras la fábrica tiene seis. Un flujo de GitHub Actions del repositorio solo ve el código del producto, no el de la fábrica. GitHub no sabe cuándo termina de desplegar Render, y el servicio anterior también responde `200`.

## Decisión
- `scripts/smoke.py` es autocontenido (solo `httpx` y la biblioteca estándar) y tiene las seis comprobaciones, con las mismas constantes y reglas que `verification/production.py`. Se copian y no se importan: el producto no depende de la fábrica. Una prueba de paridad de la fábrica comprueba que ambas dan el mismo veredicto.
- `.github/workflows/smoke.yml` se dispara con `workflow_dispatch` y con un cron diario a las 13:17 UTC (minuto 17 para evitar el pico de las horas redondas). No usa `push`, `pull_request` ni `workflow_run`.
- Permisos `contents: read`, tiempo máximo de 5 minutos y un grupo de concurrencia que no cancela la corrida en curso.
- La clave llega solo como `secrets.SMOKE_API_KEY` y la dirección como `vars.SERVICE_URL`, por `env`. Ningún valor va en el repositorio y el script nunca imprime la clave, la respuesta ni los datos inventados. Una URL o una clave vacías dan código `2` y el trabajo falla.

## Consecuencias
- Hay dos copias de la lógica de la prueba de humo; la prueba de paridad avisa si se separan, pero hay que mantener las dos.
- No corre tras cada despliegue: se lanza a mano al publicar y el resto del tiempo corre una vez al día.
- Cada corrida despierta el servicio del plan `free` y hace dos llamadas al modelo (centavos o menos).
- GitHub desactiva los flujos programados de un repositorio sin actividad en 60 días; se reactivan a mano.
- El flujo solo corre en el repositorio `hr-assistant`; en el fork de la clase, donde `product/` es una subcarpeta, queda inerte.
