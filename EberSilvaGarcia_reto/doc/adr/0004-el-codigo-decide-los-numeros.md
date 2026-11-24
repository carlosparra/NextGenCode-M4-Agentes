# 0004. El código calcula y verifica; return_direct para respuestas verificadas

- Estado: aceptada
- Fecha: 2026-11-24

## Contexto

En la evaluación con el modelo real, el subagente calculó bien que una empleada de baja
tenía 0 días, pero el supervisor (8B), al reescribir la respuesta, inventó «7 días».
Además, la caché de respuestas repitió el error.

## Decisión

- Los días de vacaciones, la plantilla y la antigüedad los calcula `app/domain/`.
- El agente de vacaciones acepta el texto del modelo solo si cita el saldo calculado; los
  casos sin saldo (no existe, baja, menos de un año) usan siempre una plantilla.
- Las herramientas que delegan en un especialista son `return_direct`: su respuesta
  verificada se entrega tal cual y el supervisor no vuelve a llamar al modelo.

## Consecuencias

- La calidad con el modelo real volvió a 100 % y cada pregunta delegada ahorra una
  llamada al modelo.
- Se pierde algo de naturalidad (la plantilla es más seca) a cambio de exactitud, que es
  lo que importa en un dato laboral.
