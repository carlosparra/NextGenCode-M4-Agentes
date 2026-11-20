---
name: iterate
description: >-
  La fábrica de la sesión 5, para mejorar un producto que ya existe · architect →
  aprobación → qa-unit → developer → costs → compuertas → qa-style → APROBACIÓN
  DE PUBLICAR → publish → Render (persona) → humo → triage (máx. 2). Ejemplo
  /iterate hr-assistant
argument-hint: "<nombre-del-repositorio> [--aprobar]"
disable-model-invocation: true
allowed-tools: >-
  Agent, Read, Write, AskUserQuestion, Bash(uv run python -m verification *),
  Bash(uv run python scripts/pipeline.py), Bash(uv run python
  scripts/publish.py *)
---
Eres el SUPERVISOR de la fábrica en modo iteración. El producto ya existe en `product/` (el de la sesión 4, con su
repositorio de git): no lo reconstruyes, lo mejoras según `spec/05-model-protocol.md`. No escribes planes, pruebas,
código ni configuración: repartes el trabajo entre especialistas (herramienta Agent) y decides qué sigue SOLO con
códigos de salida y con la primera línea de `output/qa-review.md` y de `output/triage.md`.

Entrada: $ARGUMENTS. La primera palabra es el nombre del repositorio que ya existe en GitHub (por omisión,
`hr-assistant`).
- `--aprobar` aprueba por adelantado **solo el plan** (paso 2). **Publicar siempre se pregunta** (paso 7).
- Si no puedes preguntar (por ejemplo en `claude -p`), detente en el primer punto de aprobación y explica cómo seguir.

Antes de empezar, comprueba y detente con el mensaje indicado si falla algo:
- Si `product/app/` no existe: «Copia primero el producto de la sesión 4 (ver README.md)».
- Si `product/.git` no existe: «Copia el producto con su carpeta .git: esta iteración publica sobre el repositorio que
  ya existe, no crea uno nuevo».
- Si `spec/05-model-protocol.md` no existe: «Falta la especificación de la sesión 5».
- Si `output/approved.txt` existe: «Es la aprobación de una corrida anterior. Bórralo para que esta corrida pida la
  suya: sin eso, la aprobación para publicar no significaría nada».

Después, escribe `output/activity.jsonl` vacío: la bitácora del hook empieza con esta corrida.
Lleva una bitácora: una línea por paso con lo que pasó.

1. **Plan.** Lanza `architect` con: «Actualiza el plan para spec/05-model-protocol.md. El producto ya existe en
   product/: planea solo lo que cambia».
2. **Aprobación del plan.** Muestra `output/plan.md` y pregunta: «¿Apruebas el plan? Escribe si o tus comentarios».
   Con comentarios, relanza `architect` con ellos. Máximo 2 rechazos; al tercero → ESCALAR (paso 10).
3. **Pruebas primero.** Lanza `qa-unit` con: «Agrega las pruebas de spec/05-model-protocol.md».
   Corre `uv run python -m verification unit`; debe FALLAR (rojo).
   Corre `uv run python -m verification contract`; debe FALLAR (rojo): el contrato nuevo ya existe y el producto
   todavía no cumple. Si alguno de los dos pasa, las pruebas no detectan el problema → ESCALAR.
4. **Implementar, uno por uno.** Los dos tocan archivos distintos de `product/app/`, pero ambos corren `unit` sobre los
   mismos archivos de cobertura: por eso van en orden, no en paralelo.
   - `developer` con «Implementa los puntos 2 y 3 de spec/05-model-protocol.md en el bucle del agente. Los puntos
     que no son tuyos los hace otro agente después».
   - `costs` con «Implementa el punto 1 de spec/05-model-protocol.md en la clase del modelo real. No cambies la URL del
     gateway ni el contrato de la clase».
5. **Compuertas (máximo 2 correcciones).** Corre en orden `unit`, `contract`, `qa`, `e2e` y `evaluate`, cada uno con
   `uv run python -m verification <nombre>`. Al primer fallo decide quién corrige:
   - Una prueba unitaria mal escrita → `qa-unit`.
   - Falla la lectura de la salida del modelo, la corrección o el bucle del agente → `developer`.
   - Falla lo que se manda al modelo real (mensaje `system`, petición al gateway) o falta una librería → `costs`.
   - Una prueba e2e mal escrita → `qa-e2e`.

   Vuelve a empezar este paso. Tras 2 correcciones sin pasar → ESCALAR.
6. **Evaluador-optimizador (máximo 2 vueltas).** Lanza `qa-style` con «Revisa el producto». Si la primera línea de
   `output/qa-review.md` es `CAMBIOS`, manda cada hallazgo a su dueño:
   - Código del bucle (`agent.py`) → `developer`. Código del modelo (`llm.py`) y el resto de `product/app/` → `costs`.
   - Pruebas → `qa-unit`.
   - Documentos → `architect`.

   Repite el paso 5 y lanza `qa-style` con «Revisa el producto (segunda vuelta)». Tras 2 vueltas con CAMBIOS → ESCALAR.
7. **Aprobación para publicar (humano en el lazo).** Lee `product/.git/config` y muestra un resumen de lo que se va a
   publicar:
   - Los archivos que cambiaron, según los resúmenes de los agentes.
   - El repositorio existente al que se hace el push (el remoto `origin`).
   - Que no hay secretos nuevos que poner en Render.

   Pregunta: «¿Publico estos cambios en el repositorio existente para que Render los redespliegue? Escribe si o no».
   - Con «no» → DETENIDA POR LA PERSONA (paso 10).
   - Con «si» → escribe `output/approved.txt` con la fecha y la frase «Aprobado por la persona».
8. **Publicar.** Corre `uv run python scripts/publish.py <nombre-del-repositorio>`. Si falla → ESCALAR.
   Luego dile a la persona, en pasos numerados, que:
   1. Abra la pestaña Actions del repositorio y vea las cuatro etapas.
   2. Espere a que Render termine de redesplegar solo (publica si el pipeline pasa).
   3. Cuando el servicio esté Live, le pase la URL y defina `SMOKE_API_KEY` en su terminal, sin pegarla aquí.
   4. Abra la página, escriba su clave y pregunte «¿Quién es EMP-0004?» con el modelo pequeño: debe contestar con
      Jorge Díaz. La prueba de humo no lo comprueba.

   Espera la URL.
9. **Humo y triage (máximo 2 ciclos).** Corre `uv run python -m verification production <url>`.
   - Si pasa → LISTA.
   - Si falla → lanza `triage` con la salida y lee la primera línea de `output/triage.md`:
     - `security`, `deploy`, `developer` o `costs` → relánzalo con el diagnóstico. Corre las compuertas del paso 5 y
       luego `scripts/publish.py` de nuevo (el push redespliega), y repite este paso.
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
