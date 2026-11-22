# 0005. Métricas en memoria por proceso

## Contexto
Se pide `GET /metrics` con peticiones, tasa de error, latencia p50/p95, tokens y cumplimiento del SLO, sin sumar infraestructura nueva.

## Decisión
Un colector en memoria, con candado y una ventana acotada de latencias, se alimenta desde el middleware. `/metrics` responde las cifras de este proceso e incluye su `pid`. `slo.met` es `true` si el p95 está por debajo de `SLO_P95_MS`.

## Consecuencias
- No hay dependencias nuevas y el servicio sigue sin estado de negocio entre peticiones.
- Con varias copias cada una informa solo lo suyo; las cifras globales requieren agregación externa (mejora futura).
- Al reiniciar el proceso las cifras vuelven a cero.
- Los percentiles se calculan sobre la ventana, no sobre toda la historia.
