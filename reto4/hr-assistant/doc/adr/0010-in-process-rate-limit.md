# 0010. Límite de peticiones por cliente en memoria del proceso

## Contexto

Un cliente con clave válida podría agotar la cuota del modelo. La especificación pide un límite por cliente por
minuto con `429` y `Retry-After`, y un reloj inyectado. La API es sin estado (ADR 0001) y no hay un almacén
compartido; en Render el plan gratuito corre una sola copia.

## Decisión

- `ratelimit.py` define `RateLimiter(limit_per_minute, clock)` con ventana deslizante de 60 segundos: por cliente,
  una `deque` con los instantes (`clock.monotonic()`) de sus peticiones aceptadas.
- `check(client)` descarta los instantes con más de 60 s; si quedan `limit` o más, devuelve los segundos que faltan
  para que salga el más viejo (`ceil`, mínimo 1); si no, registra la petición y devuelve `None`.
- La dependencia `require_client` (ADR 0009) llama a `check` después de autenticar. Con espera, lanza
  `HTTPException(429, "rate limit exceeded", headers={"Retry-After": str(segundos)})`.
- Cuentan las dos rutas protegidas; las peticiones sin clave válida no cuentan.

## Consecuencias

- Determinista en pruebas: un reloj falso avanza el tiempo sin dormir.
- La memoria está acotada: clientes configurados por `limit` instantes cada uno.
- Es un estado por proceso, una excepción acotada al ADR 0001: con N copias el límite real es N veces el
  configurado. Si se escala, el límite debe pasar a un almacén compartido o al borde (Render, Cloudflare).
- Los intentos con claves inválidas no se limitan aquí; cada uno cuesta solo una comparación.
