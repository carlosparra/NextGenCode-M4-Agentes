# Reporte de la fábrica: reto (spec/05-reto.md)

**Estado:** LISTA

**URL pública:** https://hr-as-tt35.onrender.com

**Repositorio:** https://github.com/jjmoramx/hr-as (commit `ad673a8` en `main`)

## Ciclos

- Rechazos del plan: 0. El plan se aprobó con 5 comentarios, que architect integró.
- Correcciones en las compuertas: 1 de 2. qa-unit acortó una docstring de `tests/test_least_privilege_tools.py` que medía 89 caracteres (el límite es 88).
- Vueltas de qa-style: 1 de 2, con resultado APROBADO.
- Ciclos de triage: 0. La prueba de humo pasó a la primera.

## Evaluación (`verification evaluate`)

| Corrida | Calidad | Costo (USD) | Tokens de entrada |
|---|---|---|---|
| Línea base | 100% | 0.001635 | 3658 |
| Palancas | 100% | 0.000225 | 2860 |

## Bitácora

1. **Inicio.** `product/app/` existe y `output/activity.jsonl` empezó vacía.
2. **Paso 1, plan.** architect escribió `output/plan.md` y los ADR 0013, 0014 y 0015, y actualizó `doc/architecture.md`.
3. **Paso 2, aprobación.** La persona aprobó el plan con 5 comentarios:
   - Acepta las tres decisiones abiertas y el cambio de `index.html`.
   - `eval_set.json` ya estaba listo.
   - deploy corre en paralelo en el paso 4.
   - El enrutador compara palabras completas.

   architect integró los comentarios en el plan y en los ADR 0008 y 0013.
4. **Paso 3, pruebas primero.** qa-unit escribió 25 pruebas nuevas. `verification unit` dio FAIL (rojo), como se esperaba.
5. **Paso 4, especialistas en paralelo.**
   - developer: datos, mínimo privilegio, `get_vacation_balance`, `department_summary` y el modelo simulado.
   - security: PII, filtro de salida, configuración, compliance, métricas, `main.py`, enrutador, la página y los documentos.
   - qa-e2e: 6 pruebas de punta a punta.
   - deploy: `PII_REDACTION=true` en `render.yaml`.
   - Al final, architect revisó la documentación del punto 10 y ajustó los ADR 0013 y 0014.
6. **Paso 5, compuertas.**
   - Primera pasada: `unit` OK, `contract` OK y `qa` FAIL por una línea larga en una prueba. La corrigió qa-unit (corrección 1).
   - Segunda pasada: `unit`, `contract`, `qa`, `e2e` y `evaluate`, todos OK. `unit` corrió 126 pruebas con 96.84 % de cobertura.
7. **Paso 6, revisión de estilo.** qa-style dio APROBADO en la primera vuelta. Anotó dos cosas menores:
   - No encontró el ADR 0015, pero el archivo existe.
   - Los ADR siguen con estado «propuesto».
8. **Paso 7, aprobación para publicar.** La persona respondió «si» y se escribió `output/approved.txt`.
9. **Paso 8, publicación.** `scripts/publish.py hr-as` dio OK: hubo push a `main` y Render redesplegó.
10. **Paso 9, prueba de humo.**
    - Mi shell no veía `SMOKE_API_KEY` y salió con código 2. No fue una falla del producto.
    - La persona corrió `verification production` en su terminal y salió con código 0: `/health` respondió 200, `/ask` sin clave 401 y `/ask` con clave 200.
11. **Paso 10, cierre.** `scripts/pipeline.py` registró 20 pasos en `output/pipeline.md`.

## Pipeline

Ver [output/pipeline.md](pipeline.md).
