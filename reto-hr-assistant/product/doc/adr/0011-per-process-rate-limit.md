# 0011. Límite de peticiones por cliente, en memoria del proceso

Estado: propuesto

## Contexto

Un cliente con clave válida puede agotar la cuota del modelo o la del plan gratuito. La API es sin estado
(ADR 0001) y no hay un almacén compartido; el plan `free` de Render corre una sola instancia.

## Decisión

`security.RateLimiter` guarda, por nombre de cliente, las marcas de tiempo de sus peticiones del último minuto
(ventana deslizante de 60 s) usando el `Clock` inyectado (`monotonic`). Se aplica después de autenticar y antes de
validar el cuerpo. Al pasar de `RATE_LIMIT_PER_MINUTE` responde `429 {"detail": "rate limit exceeded"}` con
`Retry-After` = segundos que faltan para liberar el turno más viejo, redondeado hacia arriba y mínimo 1.

## Consecuencias

- Es estado del proceso, como las métricas (ADR 0005): no cambia las respuestas, solo cuántas se aceptan.
- Con N copias el cupo real es N veces el configurado. Si se escala horizontalmente, se reemplaza por un
  almacén compartido sin tocar la dependencia.
- La memoria está acotada: solo hay entradas para clientes de `API_KEYS`, nunca para claves desconocidas o IPs.
- El reloj falso hace las pruebas deterministas: se avanza el tiempo en lugar de esperar.
