# ADR 0011: Límite de peticiones por cliente, en memoria y con reloj inyectado

## Contexto

Un cliente no debe poder agotar la cuota del modelo. La API es sin estado (ADR 0001) y el producto no tiene base de
datos ni Redis. Las pruebas deben ser deterministas, sin esperar un minuto real.

## Decisión

- `ratelimit.RateLimiter(limit, clock)` usa una ventana fija de 60 segundos por cliente. La ventana empieza con la
  primera petición del cliente; guarda su inicio y un contador, protegidos con un `threading.Lock`.
- La hora es una lectura de `clock.monotonic()` del reloj inyectado. `ClientGuard` le pasa a `check(client, now=...)`
  la lectura que ya tomó el middleware al llegar la petición; si falta, `RateLimiter` lee el reloj él mismo.
- Pasado `RATE_LIMIT_PER_MINUTE`, responde `429 {"detail": "rate limit exceeded"}` con `Retry-After`: los segundos que
  faltan para que cierre la ventana, redondeados hacia arriba y nunca menos de 1. Una petición negada no gasta cupo.
- Se revisa después de autenticar. Las peticiones con clave inválida no gastan cupo de nadie.
- Es estado operativo por proceso, igual que las métricas (ADR 0005), no estado de negocio.

## Consecuencias

- Con N copias, el límite efectivo es N veces el configurado. En Render `free` hay una sola copia, y el
  `Dockerfile` arranca `uvicorn` sin `--workers`, es decir, con un solo proceso.
- La ventana fija permite hasta el doble del límite en el borde de dos ventanas. Es aceptable para este uso.
- Un límite global exigiría un almacén compartido. Eso sería otro ADR.
