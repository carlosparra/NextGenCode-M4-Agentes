# 0005. Métricas en memoria por proceso en `GET /metrics`

Estado: propuesto

## Contexto

Se pide `GET /metrics` con peticiones, tasa de error, latencia p50/p95, tokens y cumplimiento del SLO. La API es
sin estado (ADR 0001) y no hay base de datos ni servidor de métricas disponibles en esta sesión.

## Decisión

Cada proceso lleva un objeto `Metrics` en memoria, protegido con `threading.Lock`: contadores de peticiones y de
errores (status >= 500), suma de tokens y una ventana de las últimas 1000 latencias. Los percentiles se calculan
por rango más cercano sobre esa ventana; `slo.met` es `p95 < SLO_P95_MS`. La respuesta incluye el `pid` para
saber qué copia contestó. Se cuentan todas las rutas, incluidas `/health` y `/metrics`.

## Consecuencias

- No rompe el "sin estado": las métricas no influyen en ninguna respuesta del asistente y perderlas al
  reiniciar no pierde datos de negocio.
- Con varias copias, cada una reporta solo lo suyo; agregarlas es trabajo de un recolector externo futuro.
- La memoria queda acotada por la ventana; p95 refleja tráfico reciente, no histórico.
- Los chequeos frecuentes de `/health` bajan el p95; se documenta en el README.
