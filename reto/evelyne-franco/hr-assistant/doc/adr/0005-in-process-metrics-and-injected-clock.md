# ADR 0005: Métricas en memoria del proceso y reloj inyectado

## Contexto

La spec pide `GET /metrics` con conteo, tasa de error, latencia p50/p95, tokens y
cumplimiento de un SLO. El ADR 0001 dice que la API no guarda estado entre
peticiones, y QA.md prohíbe leer la hora directamente.

## Decisión

- `Metrics` vive en memoria de cada proceso y se reporta con su `pid`. Es estado
  operativo, no de negocio: no afecta respuestas y perderlo no daña nada.
- Las latencias se guardan en una ventana circular acotada (1000 muestras); los
  contadores y tokens son acumulados. Un lock protege las escrituras.
- `slo.met` es `true` solo si p95 es estrictamente menor que `SLO_P95_MS`.
- Un protocolo `Clock` (`now()` en UTC y `monotonic()`) se inyecta en
  `create_app`; `SystemClock` es el único lugar que toca el reloj real.

## Consecuencias

- Se mantiene el principio sin estado para los datos del usuario; escalar sigue
  siendo correr más copias.
- Con varias copias, cada una reporta lo suyo; agregar entre copias (Prometheus u
  otro) queda para otra sesión.
- Las pruebas fijan el tiempo y comprueban latencias y SLO de forma determinista.
