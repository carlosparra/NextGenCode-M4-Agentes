# Reporte de la fábrica: Adenda 1, vacaciones por empleado

**Estado:** LISTA

**URL pública:** https://hr-assistant-m1rp.onrender.com

Esta vuelta implementó solo la Adenda 1 de `spec/06-multiagente.md`. Los puntos 1 a 8 ya estaban en producción
desde la corrida anterior, en `output/corrida-3-multiagente/`.

## Qué se agregó

No se agregaron agentes. Los que ya existían ganaron capacidades:

- **guard:** convierte los ids escritos de otra forma («empleado 004», «emp-4», «EMP4») en `EMP-0004`, después de
  ocultar la PII. Lo hace el módulo nuevo `app/employee_ids.py`.
- **supervisor:** tiene una regla nueva, `rule:policy_employee`, para preguntas de vacaciones con id. Se revisa
  antes que `rule:employee` y no llama al modelo.
- **policy:** tiene una herramienta nueva, `vacation_days`, en `app/vacations.py`. Calcula los días en código con el
  reloj inyectado. El agente `directory` no la tiene.
- **reviewer:** acepta los números de `vacation_days`. Si el modelo escribe un número que no sale de ninguna fuente,
  la respuesta se cambia por la frase de A5 y queda un evento `ungrounded`.

**Traza raíz:** sigue igual. Cada petición es un solo run `request` con `agent.guard`, `agent.supervisor`,
`agent.policy` y `agent.reviewer`, en ese orden. `search_policy` y `vacation_days` son runs `tool` dentro de
`agent.policy`. La prueba nueva `test_vacations_by_employee_trace_both_tools_inside_the_policy_agent` lo comprueba.

## Correcciones y vueltas de QA

- **Rechazos del plan:** 0.
- **Correcciones de compuertas:** 1 de 2. `qa` falló por dos avisos de pylint en las pruebas: C1803 y R0801 en
  `tests/test_reviewer.py` y `tests/test_vacations.py`.
  - La corrigió `qa-unit` y no `developer`, porque el error estaba en las pruebas y `developer` no las escribe.
  - En la misma corrección, `qa-unit` agregó la prueba de la traza raíz con `rule:policy_employee`.
- **Vueltas de qa-style:** 1 de 2. Veredicto APROBADO, sin hallazgos.
- **Humo y triage:** 1 ciclo. La prueba de humo pasó, así que no hizo falta triage.

## Compuertas

| Compuerta | Resultado |
|---|---|
| unit | OK: 201 pruebas, cobertura 96.76 % |
| contract | OK: 34 pruebas |
| qa | OK: pylint 10.00/10 |
| e2e | OK: 5 pruebas |
| evaluate | OK |
| production | OK: `/health` 200, `/ask` sin clave 401, `/ask` con clave 200 |

### Tabla de evaluate

| Variante | Calidad | Costo (USD) | Tokens de entrada |
|---|---|---|---|
| baseline | 100 % | 0.000914 | 1708 |
| con palancas | 100 % | 0.000125 | 1138 |

Ninguna pregunta de `evaluate` pasa por `rule:policy_employee`. La Adenda la prueban `unit` y los cinco
escenarios Gherkin.

## Decisiones que conviene saber

- Solo `vacation_days` revisa el formato del id antes de dejar `audit`. Las demás herramientas dejan `audit`
  aunque el argumento sea inválido. Está documentado en `doc/security.md`.
- Hay un falso positivo conocido: «emp 2021» se convierte en `EMP-2021`. También está en `doc/security.md`.
- No se escribió el ADR 0016 que proponía el plan. Esta fábrica pide actualizar el ADR 0014 y no escribir uno
  nuevo.

## Bitácora

1. Se comprobaron los requisitos: existen `product/app/` y `product/.git`.
2. `architect` escribió `output/plan.md` para la Adenda 1.
3. La persona aprobó el plan («si»), sin rechazos.
4. `qa-unit` agregó 24 pruebas con reloj fijo: 5 escenarios Gherkin y 19 unitarias. `verification unit` dio rojo,
   como debía.
5. `developer` implementó A1 a A7: dos archivos nuevos y 11 cambiados en `product/app/`.
6. `observability` revisó la traza raíz y actualizó `product/README.md`.
7. Compuertas, primera pasada: `unit` y `contract` pasaron, y `qa` falló por pylint en las pruebas.
8. Corrección 1: `qa-unit` corrigió los dos avisos y agregó la prueba de la traza raíz.
9. Compuertas, segunda pasada: pasaron `unit`, `contract`, `qa`, `e2e` y `evaluate`.
10. `architect` actualizó `architecture.md`, `security.md` y el ADR 0014, sin ADR nuevo.
11. `qa-style`, vuelta 1: APROBADO.
12. La persona aprobó publicar («si»). Se escribió `output/approved.txt`.
13. `scripts/publish.py` hizo el commit `45f31cf` y el push a `main`.
14. La persona confirmó el CI en verde y Render en Live («listo»).
15. `verification production` dio OK.
16. `scripts/pipeline.py` dibujó 17 pasos.

**Pipeline:** [output/pipeline.md](pipeline.md)
