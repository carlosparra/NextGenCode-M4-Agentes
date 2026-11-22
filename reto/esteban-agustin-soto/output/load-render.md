# Prueba de carga: render

Servicio medido: https://hr-assistant-lhob.onrender.com
Primera respuesta de `/health`: 0,22 s.

Latencias en milisegundos de las respuestas 200, medidas desde la máquina que corre la prueba.

| Usuarios | Peticiones | Peticiones/s | p50 | p95 | p99 | 200 | 429 | 502 | Otros errores | Nota |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 9 | 0.11 | 980 | 1200 | 1200 | 9 | 0 | 0 | 0 | cumple |
| 2 | 17 | 0.20 | 920 | 1100 | 1100 | 17 | 0 | 0 | 0 | cumple |
| 3 | 25 | 0.29 | 890 | 1200 | 1200 | 25 | 0 | 0 | 0 | cumple |
| 10 | 156 | 5.37 | 870 | 1600 | 1800 | 49 | 107 | 0 | 0 | (límite) supera a propósito el límite por cliente |

Mayor escalón sin errores que cumple la meta de 2000 ms (SLO): 3 usuarios.

No se pudo leer `/metrics` del servicio.
