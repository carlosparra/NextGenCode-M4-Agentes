# 0015. Caché de respuestas en memoria (palanca 5)

Estado: aceptado

## Contexto

Muchas preguntas de RH se repiten («¿Quién es EMP-0004?»). La caché de AI Gateway (ADR 0009) ahorra por llamada al
modelo, pero el agente igual hace varias vueltas y no aplica al modelo simulado. Una caché de respuesta completa
evita todo el bucle.

## Decisión

- `app/cache.py` define `ResponseCache`: LRU en memoria de `RESPONSE_CACHE_SIZE` entradas, con TTL
  `RESPONSE_CACHE_TTL_SECONDS` (0: apagada), reloj inyectado propio y `threading.Lock`.
- Clave: pregunta normalizada (ya enmascarada) + modelo elegido por el enrutador + ventana de historial que se
  mandaría al modelo.
- Se consulta después de PII y antes del agente. Con hit: misma `answer`, `steps` y `tools_used`; tokens y
  `cost_usd` en 0; `cache: "hit"`. Con miss: `cache: "miss"`. Sin caché el campo no aparece.
- Nunca se guarda una respuesta si la entrada tenía PII ni si la salida fue bloqueada.
- `/metrics` reporta `cache.hits` y `cache.misses`.

## Consecuencias

- Una pregunta repetida cuesta 0 y responde en milisegundos; baja `cost_usd_per_request`. Medido con
  `verification evaluate` (cada pregunta dos veces), tal cual:

  ```
  baseline  quality=100% cost_usd=0.002765 input_tokens=6514 ahorro=0%
  levers    quality=100% cost_usd=0.000388 input_tokens=5374 ahorro=86%
  cache     quality=100% cost_usd=0.000194 input_tokens=2687 ahorro=93%
  ```

  Calidad 100 %, costo 0.000194 USD contra 0.000388 USD solo con palancas 1 a 3 (la mitad) y 93 % menos que la
  línea base (`doc/cost-analysis.md`). Las cifras subieron contra la medición anterior porque el prompt de sistema
  es más largo (prohíbe datos fuera del directorio, ADR 0014); el ahorro relativo no cambió.
- La caché es por proceso (ADR 0016): con varios workers el hit rate baja y se pierde al reiniciar.
- Una respuesta puede quedar vieja hasta que venza el TTL; aceptable porque el directorio es de solo lectura y el
  TTL en Render es de 300 s.
- Memoria acotada por `RESPONSE_CACHE_SIZE`; no hay caché compartida (Redis) para no agregar infraestructura.
