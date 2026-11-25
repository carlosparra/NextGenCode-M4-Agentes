# Evaluación de costos (fake)

15 preguntas x 2 pasadas, con 10 mensajes de historial.

| Configuración | Calidad | Tokens entrada | Tokens salida | Llamadas | Costo USD | Ahorro | Latencia media ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| línea base | 100% | 18562 | 1326 | 72 | 0.008426 | 0.0% | 3.2 |
| + routing | 100% | 18562 | 1326 | 72 | 0.002443 | 71.0% | 2.8 |
| + history_window | 100% | 16890 | 1326 | 72 | 0.007936 | 5.8% | 3.0 |
| + compact_prompts | 100% | 13888 | 1326 | 72 | 0.007057 | 16.3% | 2.6 |
| + answer_cache | 100% | 9281 | 663 | 36 | 0.004213 | 50.0% | 2.9 |
| todas las palancas de la app | 100% | 6108 | 663 | 36 | 0.000972 | 88.5% | 2.6 |
