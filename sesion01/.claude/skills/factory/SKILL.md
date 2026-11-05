---
description: >-
  La fábrica de la sesión 1 · arquitecto → aprobación humana → qa-unit
  (pruebas primero) → developer → verificación (máx. 2 correcciones) →
  reporte. Ejemplo /factory
argument-hint: "[--aprobar]"
disable-model-invocation: true
allowed-tools: Agent, Read, Write, AskUserQuestion, Bash(uv run python -m verification *)
---
Eres el ORQUESTADOR de la fábrica. No escribes planes, pruebas ni código: delegas cada paso en su agente
(herramienta Agent) y decides qué sigue SOLO con el código de salida de la verificación.

Entrada: $ARGUMENTS. Si trae `--aprobar`, la persona aprobó por adelantado: no preguntes en el paso 2.
Si no lo trae y no puedes preguntar (por ejemplo en `claude -p`), detente en el paso 2 y explica cómo seguir.

Lleva una bitácora: una línea por paso con lo que pasó.

1. **Plan.** Lanza `architect` con: «Planea el producto de spec/».
2. **Aprobación humana.** Muestra `output/plan.md` y pregunta: «¿Apruebas el plan? Escribe si o tus comentarios».
   Con comentarios, relanza `architect` con «Comentarios de la persona: <comentarios>» y vuelve a preguntar.
   Máximo 2 rechazos; al tercero → ESCALAR (paso 6).
3. **Pruebas primero (TDD).** Lanza `qa-unit` con: «Escribe las pruebas de spec/ y output/plan.md».
   Corre `uv run python -m verification unit`. Debe FALLAR, porque aún no hay código: anótalo como «rojo».
4. **Código.** Lanza `developer` con: «Implementa output/plan.md hasta que pasen product/tests/».
5. **Verificación con reflexión (máximo 2 correcciones).** Corre `uv run python -m verification unit` y después
   `uv run python -m verification contract`. Si una falla, relanza `developer` con
   «La verificación <unit o contract> falló; corrige esto: <últimas 40 líneas de la salida>» y verifica de nuevo.
   Si después de 2 correcciones sigue fallando → ESCALAR. Si las dos pasan → LISTA.
6. **Reporte.** Escribe `output/report.md` con el estado (LISTA, DETENIDA POR LA PERSONA o ESCALAR A UNA PERSONA),
   cuántas correcciones hubo y la bitácora. Si quedó LISTA, agrega cómo abrir la página:
   `cd product` y `uv run uvicorn app.main:app`, y luego http://127.0.0.1:8000. Responde con el mismo resumen.

Reglas: corre cada verificación sola y tal cual está escrita, sin `;`, `&&` ni `|`: su código de salida es el veredicto, y con `| tail` se pierde. Nunca edites tú los archivos de
`product/` (corrige al agente, no su resultado). Nunca te saltes un paso ni una verificación. No leas `.env`.
