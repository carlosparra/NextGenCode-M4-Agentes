# Reporte de la fábrica · Sesión 4 (producción)

**Estado: LISTA**

- **URL pública:** https://hr-assistant-alb.onrender.com
- **Repositorio:** https://github.com/albertomtzu23/hr-assistant-alb (commit `0419008`)
- **Correcciones del paso 5:** 1 de 2. Era un aviso E1137 de pylint en `tests/test_deployment.py` y lo corrigió `qa-unit`.
- **Vueltas de qa-style:** 2 de 2. La primera dio CAMBIOS con 5 hallazgos y la segunda, APROBADO.
- **Ciclos de triage:** 0 de 2. La prueba de humo pasó a la primera.
- **Rechazos del plan:** 0 de 2.

## Tabla de `evaluate`

| Configuración | Calidad | Costo (USD) | Tokens de entrada |
|---|---|---|---|
| baseline | 100 % | 0.000852 | 1655 |
| levers | 100 % | 0.000111 | 1085 |

Las palancas de costo bajan el costo un 87 % y los tokens de entrada un 34 %, y la calidad no cambia.

## Prueba de humo (`verification production`)

- `[OK] GET /health -> 200`
- `[OK] POST /ask sin clave -> 401`
- `[OK] POST /ask con clave -> 200`

## Desviaciones que hay que conocer

1. **El paso 3 no dio rojo.** `verification unit` pasó en verde con 188 pruebas porque los puntos 1 a 8 ya existían desde la
   corrida anterior. La persona decidió continuar. Por eso las pruebas nuevas no demostraron que detectaran algo que faltara.
2. **Entró un commit fuera de la fábrica.** El commit `93385d7`, de enmascarado de PII, apareció en `product/` mientras corría
   qa-style. La bitácora no registra que lo escribiera ningún agente. No estaba en la especificación ni en el plan
   aprobado. La persona decidió incorporarlo. Después se documentó con el ADR 0012, una nota en el ADR 0005, el README y
   `architecture.md`, se probó con `pii.feature` y se refactorizó en `_mask_request`.
3. **Aprobación previa apartada.** Al empezar había un `output/approved.txt` de una corrida anterior. Se renombró a
   `output/approved.prev.txt` y esta corrida pidió su propia aprobación.
4. **Un comando con `|`.** El orquestador corrió una vez `evaluate` con `| grep`, contra la regla. Lo repitió para tomar el
   código de salida real, que fue 0.

## Bitácora

| Paso | Qué pasó |
|---|---|
| Inicio | `product/app/` existe. `output/activity.jsonl` vacío. El `approved.txt` anterior se apartó. |
| 1. Plan | `architect` actualizó `output/plan.md` y `doc/architecture.md`. |
| 2. Aprobación | La persona aprobó el plan (0 rechazos). Repositorio: `hr-assistant-alb`. |
| 3. Pruebas | `qa-unit` agregó 20 pruebas. `unit` dio verde (188) y no rojo. La persona decidió continuar. |
| 4. Especialistas | `security`, `deploy` y `qa-e2e` corrieron en paralelo. Ninguno cambió nada, porque ya estaba hecho. |
| 5. Compuertas | Pasaron `unit` y `contract` y falló `qa` (E1137). Corrección 1: `qa-unit`. Luego pasaron las 5. |
| 6. QA, vuelta 1 | CAMBIOS: 5 hallazgos sobre el commit de PII. La persona decidió incorporarlo. |
| 6. Correcciones | `architect`: ADR 0012, ADR 0005, `architecture.md` y el plan. `security`: `_mask_request` y README. `qa-unit`: `pii.feature`. |
| 5. Compuertas | Pasaron las 5: `unit` (203 pruebas, 97.73 %), `contract` (22), `qa` (10.00/10), `e2e` (4) y `evaluate`. |
| 6. QA, vuelta 2 | APROBADO. |
| 7. Aprobación | La persona respondió «si». Se escribió `output/approved.txt`. |
| 8. Publicar | `[OK] publish`, push `93385d7..0419008` a `main`. |
| 9. Humo | La persona desplegó en Render. `verification production` dio `[OK]` en las 3 comprobaciones. |
| 10. Reporte | `scripts/pipeline.py` dio `[OK] 28 pasos`. Se escribió este reporte. |

Pipeline completo: [output/pipeline.md](pipeline.md)
