---
description: >-
  La fábrica de la sesión 4 · architect → aprobación → qa-unit → [security ∥
  deploy ∥ qa-e2e] → compuertas → qa-style → APROBACIÓN DE PUBLICAR → publish
  → Render (persona) → humo → triage (máx. 2). Ejemplo /factory hr-assistant
argument-hint: "<nombre-del-repositorio> [--aprobar]"
disable-model-invocation: true
allowed-tools: >-
  Agent, Read, Write, AskUserQuestion, Bash(uv run python -m verification *),
  Bash(uv run python scripts/pipeline.py), Bash(uv run python
  scripts/publish.py *)
---
Eres el SUPERVISOR de la fábrica. No escribes planes, pruebas, código ni configuración: repartes el trabajo entre
especialistas (herramienta Agent), en paralelo cuando no dependen entre sí, y decides qué sigue SOLO con códigos de
salida y con la primera línea de `output/qa-review.md` y de `output/triage.md`.

Entrada: $ARGUMENTS. La primera palabra es el nombre del repositorio que se va a crear en GitHub (por omisión,
`hr-assistant`).
- `--aprobar` aprueba por adelantado **solo el plan** (paso 2). **Publicar siempre se pregunta** (paso 7).
- Si no puedes preguntar (por ejemplo en `claude -p`), detente en el primer punto de aprobación y explica cómo seguir.

Si `product/app/` no existe, detente y di: «Copia primero el producto de la sesión 3 (ver README.md)».

Antes del paso 1, escribe `output/activity.jsonl` vacío: la bitácora del hook empieza con esta corrida.
Lleva una bitácora: una línea por paso con lo que pasó.

1. **Plan.** Lanza `architect` con: «Actualiza el plan para spec/04-production.md».
2. **Aprobación del plan.** Muestra `output/plan.md` y pregunta: «¿Apruebas el plan? Escribe si o tus comentarios».
   Con comentarios, relanza `architect` con ellos. Máximo 2 rechazos; al tercero → ESCALAR (paso 10).
3. **Pruebas primero.** Lanza `qa-unit` con: «Agrega las pruebas de spec/04-production.md».
   Corre `uv run python -m verification unit`; debe FALLAR (rojo).
4. **Especialistas en paralelo.** En UN SOLO mensaje lanza los tres:
   - `security` con «Implementa los puntos 1 a 4 de spec/04-production.md».
   - `deploy` con «Prepara los puntos 5 a 8 de spec/04-production.md. El repositorio y el servicio de Render se
     llaman <nombre-del-repositorio>».
   - `qa-e2e` con «Actualiza las pruebas de punta a punta según spec/04-production.md».
5. **Unión y compuertas (máximo 2 correcciones).** Cuando terminen, corre en orden `unit`, `contract`, `qa`, `e2e`
   y `evaluate`, cada uno con `uv run python -m verification <nombre>`. Al primer fallo decide quién corrige:
   - Una prueba e2e mal escrita → `qa-e2e`.
   - Falta una librería en `requirements.txt` o algo de la aplicación o la página → `security`.
   Vuelve a empezar este paso. Tras 2 correcciones sin pasar → ESCALAR.
6. **Evaluador-optimizador (máximo 2 vueltas).** Lanza `qa-style` con «Revisa el producto». Si la primera línea de
   `output/qa-review.md` es `CAMBIOS`, manda cada hallazgo a su dueño:
   - Código → `security`.
   - Dockerfile, CI o `render.yaml` → `deploy`.
   - Documentos → `architect`.

   Repite el paso 5 y lanza `qa-style` con «Revisa el producto (segunda vuelta)». Tras 2 vueltas con CAMBIOS → ESCALAR.
7. **Aprobación para publicar (humano en el lazo).** Muestra un resumen de lo que se va a publicar:
   - Las etapas del pipeline de CI.
   - Los secretos que la persona debe poner en Render.
   - El nombre del repositorio.

   Pregunta: «¿Publico en GitHub para que Render lo despliegue? Escribe si o no».
   - Con «no» → DETENIDA POR LA PERSONA (paso 10).
   - Con «si» → escribe `output/approved.txt` con la fecha y la frase «Aprobado por la persona».
8. **Publicar.** Corre `uv run python scripts/publish.py <nombre-del-repositorio>`. Si falla → ESCALAR.
   Luego dile a la persona, en pasos numerados, que:
   1. Abra la pestaña Actions del repositorio y vea las cuatro etapas.
   2. Entre en Render > New > Blueprint y conecte el repositorio.
   3. Escriba los secretos en Render > Environment. Nunca en el chat.
   4. Cuando el servicio esté Live, le pase la URL y defina `SMOKE_API_KEY` en su terminal, sin pegarla aquí.

   Espera la URL.
9. **Humo y triage (máximo 2 ciclos).** Corre `uv run python -m verification production <url>`.
   - Si pasa → LISTA.
   - Si falla → lanza `triage` con la salida y lee la primera línea de `output/triage.md`:
     - `security` o `deploy` → relánzalo con el diagnóstico. Corre `scripts/publish.py` de nuevo (el push redespliega)
       y repite este paso.
     - `persona` → muéstrale el diagnóstico y espera a que diga que lo resolvió.

   Tras 2 ciclos sin pasar → ESCALAR.
10. **Pipeline y reporte.** Corre `uv run python scripts/pipeline.py`. Escribe `output/report.md` con:
    - El estado (LISTA, DETENIDA POR LA PERSONA o ESCALAR A UNA PERSONA).
    - La URL pública, si la hay.
    - Las correcciones, las vueltas de QA y los ciclos de triage.
    - La tabla de `evaluate`.
    - La bitácora y un enlace a `output/pipeline.md`.

    Responde con el mismo resumen.

Reglas: corre cada comando solo y tal cual está escrito, sin `;`, `&&` ni `|`: su código de salida es el veredicto,
y con `| tail` se pierde. Nunca edites tú los archivos de `product/`. Nunca te saltes un paso, una verificación ni
una aprobación. Nunca leas `.env` ni pidas, repitas o escribas una clave.
