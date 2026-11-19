# 0012. Límite de peticiones por cliente, en memoria y con reloj inyectado

Estado: aceptado

## Contexto

Más de `RATE_LIMIT_PER_MINUTE` peticiones de un cliente en un minuto deben responder 429 con `Retry-After`. El reloj
se inyecta (QA.md pide pruebas deterministas). Render free corre una sola copia y no hay Redis ni otra
infraestructura.

## Decisión

- `RateLimiter(limit, clock)` en `ratelimit.py` guarda, por cliente, una ventana deslizante de 60 s con los
  instantes de `clock.monotonic()` de las peticiones aceptadas, protegida con `threading.Lock`.
- Se revisa en `require_client`, después de autenticar: sin cliente no hay cuenta.
- Si se pasa: `429 {"detail": "rate limit exceeded"}` y
  `Retry-After = max(1, ceil(más_antiguo + 60 - ahora))`. Las rechazadas no se cuentan.
- Se inyecta en `create_app(rate_limiter=...)`, como `Metrics` (ADR 0005).

## Consecuencias

- Es estado de protección, no de conversación: el ADR 0001 sigue vigente para las respuestas.
- Con varias copias, cada una cuenta aparte y el límite real se multiplica. Al escalar, se cambia por un almacén
  compartido sin tocar las rutas.
- La memoria está acotada: solo hay clientes configurados y, cada uno, a lo más `limit` instantes.
- Reiniciar el proceso pone las cuentas en cero.
