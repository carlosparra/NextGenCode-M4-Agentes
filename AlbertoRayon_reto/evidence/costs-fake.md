Proveedor: `fake` | casos: 2 pasadas del set de evaluación

| Configuración | Calidad | Costo USD | Tokens | Latencia media | Ahorro |
| --- | ---: | ---: | ---: | ---: | ---: |
| Línea base (sin palancas) | 100% | 0.005527 | 14060 | 3.7 ms | 0.0 % |
| + enrutamiento | 100% | 0.001544 | 14060 | 4.4 ms | 72.1 % |
| + ventana de historial | 100% | 0.005104 | 12616 | 3.7 ms | 7.7 % |
| + prompt compacto | 100% | 0.004725 | 11324 | 3.5 ms | 14.5 % |
| Palancas sin cachés | 100% | 0.001356 | 9880 | 3.3 ms | 75.5 % |
| Todas + caché de respuestas | 100% | 0.000678 | 4940 | 1.7 ms | 87.7 % |
