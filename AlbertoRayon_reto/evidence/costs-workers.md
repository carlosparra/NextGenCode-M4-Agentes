Proveedor: `workers`. Costo y tokens son promedios por pregunta.

| Configuración | Pasadas | Calidad | Costo USD | Tokens | Latencia | Ahorro |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Línea base (sin palancas) | 1 | 100% | 0.00050600 | 1137 | 2244 ms | 0.0 % |
| + enrutamiento | 1 | 93% | 0.00013984 | 1185 | 1316 ms | 72.4 % |
| + ventana de historial | 1 | 100% | 0.00046274 | 992 | 1955 ms | 8.5 % |
| + prompt compacto | 1 | 100% | 0.00042509 | 939 | 1779 ms | 16.0 % |
| Palancas sin cachés | 1 | 100% | 0.00012105 | 881 | 907 ms | 76.1 % |
| Todas + caché de respuestas | 2 | 93% | 0.00006013 | 440 | 478 ms | 88.1 % |

Falló en «+ enrutamiento»: ¿Qué clima hace hoy en Monterrey?

Falló en «Todas + caché de respuestas»: ¿Qué clima hace hoy en Monterrey?
