# Sesión 6 · Costo por petición en el log y documentación pública de la API

Parte del producto de las sesiones 1 a 5. Agrega dos cosas pequeñas que el reto pide: el costo de cada petición en el
log, para poder sumarlo desde los logs de Render, y una documentación OpenAPI completa y pública.

## Lo que debe hacer

### A. `cost_usd` en el evento `agent_run`

1. El evento `agent_run` agrega el campo `cost_usd`: el costo en dólares de esa petición.
2. Es **el mismo número** que `POST /ask` devuelve en `cost_usd`. Se calcula una sola vez; no se calcula dos veces por
   caminos distintos. Una llamada cacheada cuesta 0, como hoy.
3. Un modelo sin precio en la tabla sigue dando error, no 0 (no cambia).
4. La respuesta de `POST /ask` y `GET /metrics` no cambian. El evento `request` no cambia.
5. `cost_usd` es un número, nunca un texto; no lleva ningún dato de la persona.

### B. Documentación OpenAPI pública

1. `GET /docs` y `GET /openapi.json` responden `200` **sin clave**. Es una decisión: la documentación no tiene secretos.
   `/redoc` queda como la trae FastAPI. No se agrega ninguna variable para apagarla.
2. El esquema (`/openapi.json`) describe todas las rutas del producto: `GET /`, `GET /health`, `POST /ask` y
   `GET /metrics`. Cada una con resumen, descripción y etiqueta, escritos en español.
3. `POST /ask` documenta la petición (`question`, `history`) y la respuesta con **todos** sus campos actuales. La forma
   real de la respuesta no cambia: ni campos nuevos, ni campos menos, ni otro orden de significado.
4. `POST /ask` y `GET /metrics` documentan sus respuestas de error: `401` (clave inválida o ausente), `422` (validación),
   `429` (límite, con `Retry-After`) y `502` (modelo no disponible), con la forma que ya devuelven.
5. El esquema declara el encabezado `X-API-Key` como esquema de seguridad, para que el botón de autorizar de `/docs`
   permita probar `/ask` y `/metrics` con una clave. Sin clave, el `401` sigue siendo el de hoy
   (`{"detail": "invalid or missing API key"}`): documentar no cambia el comportamiento.
6. Ningún ejemplo ni descripción lleva una clave, una CURP ni un correo. Los ejemplos usan `EMP-0004`.
7. `README.md` tiene una sección «Documentación de la API»: dónde está (`/docs`, `/openapi.json`), que es pública, cómo
   probar `/ask` con una clave desde `/docs`, y una tabla de rutas, códigos y si piden clave.
   `doc/compliance-checklist.md` tiene una fila que dice que la documentación es pública a propósito y por qué.

## Lo que no cambia

- Las reglas de acceso: `/`, `/health` y `/docs` no piden clave; `/ask` y `/metrics` sí.
- El enmascarado de PII, el límite de peticiones y las reglas de compliance.
- La página web, las herramientas y el directorio.

## Pruebas

- **`qa-unit`**, antes del código:
  - `agent_run` trae `cost_usd` igual al de la respuesta; con una llamada cacheada vale 0; es un número.
  - La respuesta de `/ask` sigue teniendo exactamente los mismos campos de hoy.
  - `/docs` y `/openapi.json` dan `200` sin clave; el esquema trae las cuatro rutas, los códigos `401`, `422`, `429` y
    `502` de `/ask`, y el esquema de seguridad `X-API-Key`.
  - Sin clave, `/ask` y `/metrics` siguen dando `401` con el mismo cuerpo.
  - El esquema serializado no contiene ninguna clave de cliente, CURP ni correo.
- **`qa-e2e`**: ninguna. `/docs` carga su interfaz desde un CDN y haría la prueba depender de la red; el esquema se
  comprueba en las pruebas de contrato.

## Cómo se comprueba

- `verification unit`, `contract`, `qa`, `e2e` y `evaluate`, como en la sesión 5.
- `verification contract`: una prueba nueva envía una pregunta y comprueba que el `cost_usd` del evento `agent_run` del
  log capturado es el mismo que devolvió `/ask`; otra pide `/docs` y `/openapi.json` sin clave.
- `uv run python -m verification production <url>`: la prueba de humo agrega una sexta comprobación, `GET /openapi.json`
  con `200` y las rutas `/ask` y `/health` en el esquema.
- Una persona aprueba la publicación. Después de publicar, en los logs de Render, el evento `agent_run` trae `cost_usd`.
