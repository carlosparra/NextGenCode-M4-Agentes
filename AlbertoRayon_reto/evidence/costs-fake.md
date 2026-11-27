Proveedor: `fake`. Costo y tokens son promedios por pregunta.

| Configuración | Pasadas | Calidad | Costo USD | Tokens | Latencia | Ahorro |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Línea base (sin palancas) | 1 | 100% | 0.00020111 | 526 | 3 ms | 0.0 % |
| + enrutamiento | 1 | 100% | 0.00005704 | 526 | 3 ms | 71.6 % |
| + ventana de historial | 1 | 100% | 0.00018700 | 478 | 4 ms | 7.0 % |
| + prompt compacto | 1 | 100% | 0.00017438 | 435 | 3 ms | 13.3 % |
| Palancas sin cachés | 1 | 100% | 0.00005077 | 387 | 3 ms | 74.8 % |
| Todas + caché de respuestas | 2 | 100% | 0.00002538 | 193 | 2 ms | 87.4 % |
