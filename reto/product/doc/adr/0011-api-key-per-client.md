# 0011. Una clave por cliente, comprobada en una dependencia de FastAPI

Estado: aceptado

## Contexto

La sesión 4 publica el producto en Internet. `POST /ask` y `GET /metrics` deben exigir `X-API-Key`; `/`, `/health`
y `/docs` no. El nombre del cliente debe ir al log, a la auditoría y a la traza, y la clave nunca.

## Decisión

- `API_KEYS=cliente:clave,...` se valida al arrancar en `auth.parse_api_keys` (dentro de `load_settings`). Un error
  dice el número de entrada y su largo, nunca su valor. Los nombres de cliente se limitan a `[A-Za-z0-9._-]`.
- `Settings.api_keys` lleva `repr=False`.
- `ApiKeyAuthenticator` compara con `hmac.compare_digest` sobre bytes contra todas las claves y devuelve el cliente.
- Una dependencia `require_client` (creada en `build_client_dependency`) se aplica solo a `/ask` y `/metrics`.
  Lee el encabezado con `APIKeyHeader(name="X-API-Key", auto_error=False)` de FastAPI, que solo sirve para extraer
  el valor y documentar el esquema de seguridad en OpenAPI (`/docs`); con `auto_error=False` nunca responde por su
  cuenta y entrega `None` si falta el encabezado.
- La decisión de rechazo queda en `require_client`: responde `401 {"detail": "invalid or missing API key"}` y deja
  `request.state.client`. Así el código y el texto del error no dependen de la versión de FastAPI, cuyo error
  automático de `APIKeyHeader` cambió entre versiones (403 o 401).
- El cliente viaja en `bind(request_id, client)` hacia `request`, `audit`, `agent_run` y los metadatos de la traza.

## Consecuencias

- Las rutas públicas y `/docs` no cambian; `/docs` muestra el esquema `X-API-Key` para probar las rutas protegidas.
  Las pruebas de sesiones previas necesitan la clave por omisión en `conftest.py`.
- Nadie debe cambiar `auto_error` a `True`: el 401 con el `detail` exacto lo garantiza `require_client`.
- En `development` con `API_KEYS` vacía el producto arranca, pero responde 401 a todo lo protegido.
- Rotar una clave exige reiniciar el servicio (se lee al arrancar).
- Los 401 no tienen límite de peticiones; la defensa contra fuerza bruta es el largo mínimo en producción (ADR 0013).
