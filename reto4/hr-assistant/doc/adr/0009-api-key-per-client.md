# 0009. Una clave por cliente con una dependencia de FastAPI

## Contexto

El producto se publica en Internet. `POST /ask` gasta cuota del modelo y `GET /metrics` expone datos de
operación, así que deben exigir una clave. Hay que saber qué cliente hizo cada petición y la clave nunca puede
filtrarse por el log, la traza, un error o el `repr` de la configuración.

## Decisión

- `config.py` lee `API_KEYS` (`cliente:clave,...`) con `auth.parse_api_keys`. Una entrada sin `:`, con cliente o
  clave vacíos, un cliente repetido o una clave repetida lanzan `ConfigError` con la posición de la entrada y su
  largo, nunca su valor. El campo va con `repr=False`.
- `auth.py` expone `KeyRing.client_for(key)`, que recorre todas las claves con `hmac.compare_digest` y devuelve el
  nombre del cliente o `None`.
- Las rutas protegidas (`/ask`, `/metrics`) usan una dependencia `require_client` con
  `APIKeyHeader(name="X-API-Key", auto_error=False)`. Sin clave o con una inválida lanza
  `HTTPException(401, "invalid or missing API key")`. Guarda el cliente en `request.state.client`.
- `/`, `/health` y `/docs` no llevan la dependencia. Con `API_KEYS` vacía ninguna clave es válida
  (valor seguro por omisión).

## Consecuencias

- La dependencia se resuelve antes que el cuerpo: sin clave y con pregunta vacía, la respuesta es `401`, no `422`.
- Los eventos `request`, `agent_run` y `audit` llevan `client`; las trazas, `client` en los metadatos.
- Solo existe el nombre del cliente fuera de `auth.py`; la clave no se guarda en `request.state` ni se registra.
- En desarrollo hay que definir `API_KEYS` para usar la página; el README lo explica.
