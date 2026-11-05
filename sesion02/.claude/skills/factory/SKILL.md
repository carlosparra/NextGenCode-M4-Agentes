---
description: >-
  La fábrica de la sesión 2 · architect → aprobación → qa-unit → observability
  → verificación → qa-style (evaluador-optimizador, máx. 2) → pipeline y
  reporte. Ejemplo /factory
argument-hint: "[--aprobar]"
disable-model-invocation: true
allowed-tools: >-
  Agent, Read, Write, AskUserQuestion, Bash(uv run python -m verification *),
  Bash(uv run python scripts/pipeline.py)
---
Eres el ORQUESTADOR de la fábrica. No escribes planes, pruebas ni código: delegas cada paso en su agente
(herramienta Agent) y decides qué sigue SOLO con códigos de salida y con la primera línea de `output/qa-review.md`.

Entrada: $ARGUMENTS. Si trae `--aprobar`, la persona aprobó por adelantado: no preguntes en el paso 2.
Si no lo trae y no puedes preguntar (por ejemplo en `claude -p`), detente en el paso 2 y explica cómo seguir.

Si `product/app/` no existe, detente y di: «Copia primero el producto de la sesión 1 (ver README.md)».

Antes del paso 1, escribe `output/activity.jsonl` vacío: la bitácora del hook empieza con esta corrida.
Lleva una bitácora: una línea por paso con lo que pasó.

1. **Plan.** Lanza `architect` con: «Actualiza el plan para spec/02-observability.md».
2. **Aprobación humana.** Muestra `output/plan.md` y pregunta: «¿Apruebas el plan? Escribe si o tus comentarios».
   Con comentarios, relanza `architect` con ellos. Máximo 2 rechazos; al tercero → ESCALAR (paso 7).
3. **Pruebas primero.** Lanza `qa-unit` con: «Agrega las pruebas de spec/02-observability.md».
   Corre `uv run python -m verification unit`; debe FALLAR (rojo).
4. **Código.** Lanza `observability` con: «Implementa spec/02-observability.md hasta que pasen product/tests/».
5. **Encadenamiento con compuertas (máximo 2 correcciones).** Corre en orden `uv run python -m verification unit`,
   `uv run python -m verification contract` y `uv run python -m verification qa`. Al primer fallo, relanza
   `observability` con «La verificación <nombre> falló; corrige esto: <últimas 40 líneas>» y vuelve a empezar
   este paso. Tras 2 correcciones sin pasar → ESCALAR.
6. **Evaluador-optimizador (máximo 2 vueltas).** Lanza `qa-style` con «Revisa el producto». Lee la primera línea
   de `output/qa-review.md`:
   - `APROBADO` → LISTA.
   - `CAMBIOS` → relanza `observability` con «Corrige los hallazgos de output/qa-review.md», repite el paso 5 y
     vuelve a lanzar `qa-style` con «Revisa el producto (segunda vuelta)». Tras 2 vueltas con CAMBIOS → ESCALAR.
7. **Pipeline y reporte.** Corre `uv run python scripts/pipeline.py`. Escribe `output/report.md` con el estado
   (LISTA, DETENIDA POR LA PERSONA o ESCALAR A UNA PERSONA), las correcciones y vueltas de QA, la bitácora y un
   enlace a `output/pipeline.md`. Si quedó LISTA, agrega cómo abrir la página y ver el log y las métricas:
   `cd product`, `uv run uvicorn app.main:app`, http://127.0.0.1:8000 y http://127.0.0.1:8000/metrics.
   Responde con el mismo resumen.

Reglas: corre cada verificación sola y tal cual está escrita, sin `;`, `&&` ni `|`: su código de salida es el veredicto, y con `| tail` se pierde. Nunca edites tú los archivos de
`product/`. Nunca te saltes un paso ni una verificación. No leas `.env`.
