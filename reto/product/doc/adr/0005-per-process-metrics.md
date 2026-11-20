# 0005. Métricas en memoria por proceso

Estado: propuesto

## Contexto

Se pide `GET /metrics` con peticiones, tasa de error, p50/p95 de latencia, tokens y cumplimiento del SLO,
sin agregar infraestructura. El ADR 0001 dice que la API no guarda nada entre peticiones.

## Decisión

- `Metrics` vive en memoria del proceso, protegida con `threading.Lock`, y se inyecta en `create_app`.
- Es estado de observación, no de conversación: no cambia ninguna respuesta de `/ask`. El ADR 0001 sigue
  vigente para el comportamiento.
- Latencias en una ventana acotada; percentiles por rango más cercano; `met` es `p95 < SLO_P95_MS`.
- `GET /metrics` no se cuenta a sí mismo. La respuesta incluye `pid`.

## Consecuencias

- Con varias copias, cada una reporta lo suyo; la vista global se arma por fuera, agrupando por `pid`.
- Reiniciar el proceso pone las métricas en cero.
- La memoria no crece con el tráfico gracias a la ventana acotada.
- Si más adelante se usa Prometheus u otro sistema, se reemplaza `Metrics` sin tocar el agente.
