# 0011. Límite de peticiones en el proceso con reloj inyectado

## Contexto
Cada pregunta puede costar dinero y el servicio es sin estado. Se necesita un tope por cliente sin agregar infraestructura, y que las pruebas no esperen un minuto real.

## Decisión
`RateLimiter` en `security.py` cuenta peticiones por cliente en una ventana fija de un minuto, en memoria, con el reloj inyectado. Al pasar `RATE_LIMIT_PER_MINUTE` responde `429` con `Retry-After` (segundos que faltan). Solo se cuentan clientes autenticados, y el candado protege los contadores.

## Consecuencias
- Cero dependencias nuevas y pruebas deterministas.
- Con varios procesos o reinicios el límite es por proceso; vale para el plan `free` (un proceso).
- La ventana fija permite una ráfaga doble en el cambio de minuto.
- Si se escala, se cambia por un almacén compartido detrás de la misma interfaz.
