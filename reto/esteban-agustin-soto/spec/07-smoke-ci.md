# Sesión 7 · Prueba de humo automática en GitHub Actions

Parte del producto de las sesiones 1 a 6. La prueba de humo contra el servicio publicado hoy se corre a mano. Esta
sesión la pone al día y la deja correr sola en GitHub Actions, sin guardar nunca una clave en el repositorio.
**Reemplaza el punto 8 de `spec/04-production.md`** (las tres comprobaciones de `scripts/smoke.py`).

## Por qué hace falta ponerla al día

`product/scripts/smoke.py` tiene solo tres comprobaciones y solo mira códigos HTTP. La prueba de seis comprobaciones
vive en la fábrica (`verification/production.py`), y un flujo de GitHub Actions del repositorio del producto no la ve.
El flujo nuevo debe ejecutar el script del propio producto, así que ese script tiene que ser igual de completo.

## Lo que debe hacer

1. **`scripts/smoke.py` con seis comprobaciones**, en este orden, cada una con una línea `[OK]` o `[FAIL]`:
   - `GET /health` responde `200` (va primero: despierta un servicio dormido).
   - `GET /openapi.json`, sin clave, responde `200` y su esquema trae las rutas `/ask` y `/health`.
   - `POST /ask` sin clave responde `401`.
   - `POST /ask` con clave responde `200`.
   - La respuesta de `/ask` con clave nombra a «Jorge Díaz» para la pregunta «¿Quién es EMP-0004?» y no es el mensaje
     fijo de fallo («No pude completar...»).
   - Una pregunta con una CURP y un correo inventados responde `200` y el cuerpo, en cualquier combinación de
     mayúsculas, no trae ni la CURP ni el correo.
2. **Autocontenido:** solo depende de `httpx` y de la biblioteca estándar; no importa nada de la fábrica.
3. **Nunca imprime** la respuesta del servicio, la clave ni los datos inventados. Lee la clave de `SMOKE_API_KEY`,
   nunca de un argumento. Tiempo máximo de 90 s por petición. Códigos de salida: `0` todo pasa, `1` alguna falla,
   `2` falta la URL o la clave.
4. **Las mismas constantes y reglas que `verification/production.py`:** la CURP inventada `AAAA010101HDFBBB09`, el
   correo `persona.prueba@example.com`, el empleado «Jorge Díaz». Una prueba de la fábrica comprueba que las dos
   implementaciones dan el mismo veredicto ante las mismas respuestas simuladas, para que no se separen con el tiempo.
5. **`.github/workflows/smoke.yml`** en el producto:
   - Se dispara a mano (`workflow_dispatch`) y una vez al día (`schedule`). **No** se dispara con `push` ni con
     `pull_request`, ni al terminar el CI: GitHub no sabe cuándo termina de desplegar Render, y el servicio anterior
     también responde `200`.
   - `permissions: contents: read`, un tiempo máximo de 5 minutos y un grupo de concurrencia, sin cancelar la corrida
     en curso.
   - Un solo trabajo en `ubuntu-latest`: `actions/checkout` y `actions/setup-python` con las mismas versiones que
     `ci.yml`, Python 3.12, `pip install httpx` y `python scripts/smoke.py "$SERVICE_URL"`.
   - La clave llega solo como `${{ secrets.SMOKE_API_KEY }}` y la dirección como `${{ vars.SERVICE_URL }}`. Ninguna
     clave ni dirección escrita en el archivo, y ningún paso la imprime (sin `set -x`, sin `echo` de la clave).
   - Si el script falla, el trabajo falla y GitHub avisa por correo a quien administra el repositorio.
6. **Documentación:** `README.md` del producto explica el flujo, cómo crear el secreto `SMOKE_API_KEY` y la variable
   `SERVICE_URL` (sin valores) y cómo lanzarlo a mano; `doc/architecture.md` y `doc/compliance-checklist.md` lo
   reflejan (la clave de la prueba de humo es un secreto de GitHub y no está en el repositorio).

## Lo que no cambia

- `ci.yml`, `render.yaml`, el `Dockerfile` y todo `app/`.
- El despliegue: Render sigue publicando solo cuando el CI pasa. La prueba de humo automática no despliega nada.
- `verification/production.py`, la prueba de humo de la fábrica, que sigue igual.

## Límites aceptados

- No corre tras cada despliegue: se lanza a mano después de publicar, y el resto del tiempo corre una vez al día.
- Cada corrida despierta el servicio del plan `free` y hace dos llamadas al modelo (de centavos o menos).
- GitHub desactiva los flujos programados de un repositorio sin actividad en 60 días; se reactivan a mano.
- Hay dos copias de la lógica de la prueba de humo (la del producto y la de la fábrica); la prueba de paridad avisa si
  se separan, pero hay que mantener las dos.

## Pruebas

- **`qa-unit`**, antes del código, en `product/tests/` y sin agregar dependencias (el YAML se revisa como texto):
  - `scripts/smoke.py` con un servidor simulado: todo bien pasa con seis `[OK]`; falla si falta la documentación, si
    el esquema no trae `/ask` o `/health`, si `/ask` sin clave no da `401`, si con clave no da `200`, si la respuesta
    no nombra al empleado o es el mensaje de fallo, si devuelve la CURP o el correo (también en otra combinación de
    mayúsculas) y si la pregunta con datos personales da un error. Nunca imprime la respuesta ni los datos
    inventados. Sin clave o sin URL termina con `2`.
  - `smoke.yml`: tiene `workflow_dispatch` y `schedule`; no tiene `push` ni `pull_request`; usa
    `secrets.SMOKE_API_KEY` y `vars.SERVICE_URL`; tiene `permissions: contents: read` y `timeout-minutes`; no
    contiene ninguna clave escrita ni `set -x`.
- **El supervisor**, en `tests/` de la fábrica: la prueba de paridad entre `scripts/smoke.py` del producto y
  `verification/production.py`, con las mismas respuestas simuladas.

## Cómo se comprueba

- `verification unit`, `contract`, `qa`, `e2e` y `evaluate`, y `scripts/verify.py`, como en la sesión 6.
- La sintaxis del YAML se valida con un analizador, fuera del producto, antes de la aprobación.
- Una persona aprueba la publicación. Después de publicar, la persona crea el secreto `SMOKE_API_KEY` y la variable
  `SERVICE_URL` en GitHub, se lanza el flujo a mano (con su permiso) y debe terminar en verde con seis `[OK]` en el
  registro. Al día siguiente se comprueba que la corrida programada también pasó.
