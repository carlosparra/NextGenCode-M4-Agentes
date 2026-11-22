# Prueba de carga: local

Servicio medido: http://127.0.0.1:8773
Primera respuesta de `/health`: 0,01 s.

Latencias en milisegundos de las respuestas 200, medidas desde la máquina que corre la prueba.

| Usuarios | Peticiones | Peticiones/s | p50 | p95 | p99 | 200 | 429 | 502 | Otros errores | Nota |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 181 | 3.11 | 15 | 18 | 19 | 181 | 0 | 0 | 0 | cumple |
| 5 | 904 | 15.46 | 13 | 18 | 19 | 904 | 0 | 0 | 0 | cumple |
| 10 | 1828 | 31.29 | 11 | 17 | 21 | 1828 | 0 | 0 | 0 | cumple |
| 20 | 3643 | 62.40 | 9 | 16 | 19 | 3643 | 0 | 0 | 0 | cumple |
| 50 | 9098 | 154.12 | 17 | 38 | 77 | 9098 | 0 | 0 | 0 | cumple |
| 100 | 12319 | 207.41 | 160 | 320 | 470 | 12319 | 0 | 0 | 0 | cumple |

Mayor escalón sin errores que cumple la meta de 2000 ms (SLO): 100 usuarios.

Según `/metrics`: 28093 peticiones desde que arrancó el proceso, tasa de error 0.0%, p95 283.12199999999996 ms, costo acumulado 0.468754707000106 USD y meta de latencia cumplida.
El costo sale del modelo simulado: no es gasto real.
