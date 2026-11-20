# 0016. Varios workers y estado por proceso protegido con candado

Estado: aceptado

## Contexto

Un solo proceso de uvicorn limita el rendimiento: `verification load` manda 40 preguntas, 8 a la vez, y exige p95
por debajo de 5 s sin 5xx. La API ya es sin estado (ADR 0001), pero cada proceso guarda métricas (ADR 0005), el
límite (ADR 0012), la caché (ADR 0015) y el log.

## Decisión

- El contenedor arranca `uvicorn ... --workers ${WEB_CONCURRENCY:-1}`; Render usa `WEB_CONCURRENCY=2`.
- `POST /ask` sigue siendo una función síncrona: FastAPI la corre en su pool de hilos y no bloquea el bucle.
- El agente se crea por petición. Todo estado compartido del proceso (métricas, límite, caché, log) se protege con
  `threading.Lock`; no se comparte estado entre procesos.
- `/health` y `/metrics` reportan `pid` para saber qué proceso respondió.

## Consecuencias

- Más throughput sin cambiar el código de negocio; escalar sigue siendo agregar procesos o instancias.
- Las métricas, el límite y la caché son por proceso: el límite efectivo puede ser hasta `WEB_CONCURRENCY` veces
  `RATE_LIMIT_PER_MINUTE`, las métricas se agregan por fuera y la caché tiene menos aciertos.
- Un estado compartido real (Redis) queda fuera de alcance; se reconsidera si el límite exacto es requisito.
- El plan gratuito de Render tiene poca memoria: cada worker carga el producto completo, por eso solo dos.
