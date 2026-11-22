# Evaluación con el modelo real

Cada configuración se repitió 3 veces; costo y tokens son
por repetición (todas las preguntas del conjunto).

| Configuración | Calidad media | Peor calidad | Costo (USD) | Tokens de entrada | Errores |
| --- | --- | --- | --- | --- | --- |
| baseline | 100% | 100% | 0.002842 | 6269 | 0 |
| levers | 100% | 100% | 0.000464 | 5938 | 0 |
| levers + cache | 100% | 100% | 0.000153 | 6020 | 0 |

Veredicto: PASA (las palancas mantienen la calidad media y bajan el costo, sin contar la caché).
