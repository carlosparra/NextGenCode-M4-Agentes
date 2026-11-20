# ADR 0010: Una clave por cliente, validada como dependencia y nunca registrada

## Contexto

El producto se publica en Internet. `POST /ask` gasta cuota del modelo, y `GET /metrics` expone datos operativos.
Hay que saber qué cliente hizo cada petición sin que la clave aparezca en el log, en una traza o en un error. Pydantic
copia el valor de entrada en sus mensajes de validación.

## Decisión

- `API_KEYS` (`cliente:clave,...`) se interpreta en `auth.parse_api_keys`, que `config.load_settings` llama fuera de
  los validadores de Pydantic. Si una entrada está mal formada o repite una clave, el error dice su posición y su
  largo, sin el valor y sin encadenar la excepción original.
- Las claves se guardan como `SecretStr`. `auth.ApiKeyAuth.client_for` las compara con `hmac.compare_digest` contra
  todas las configuradas.
- La autenticación es una dependencia de FastAPI: la clase `ClientGuard` de `main.py`, que `create_app()` arma con
  `ApiKeyAuth` y `RateLimiter` y monta con `Depends` solo en `POST /ask` y `GET /metrics`. `GET /`, `/health` y
  `/docs` quedan abiertos.
- `ClientGuard` deja el nombre del cliente en `scope["state"]`. El middleware lo agrega al evento `request`, y el agente
  lo agrega a `agent_run`, a `audit` y a los metadatos de las trazas.
- Respuesta única para clave ausente o inválida: `401 {"detail": "invalid or missing API key"}`.

## Consecuencias

- Los 401 pasan por el middleware: quedan en el log y en las métricas, con `request_id`.
- Con `API_KEYS` vacía en desarrollo, `/ask` siempre responde 401. Las pruebas y el contrato mandan una clave de
  prueba.
- Rotar una clave exige reiniciar el proceso. Es aceptable para pocos clientes.
