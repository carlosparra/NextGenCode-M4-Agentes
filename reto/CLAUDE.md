# Fábrica del HR Assistant (Módulo 4, reto: producción operable)

Los agentes construyen el producto en `product/` a partir de la especificación de `spec/`. La última es
`spec/05-reto.md` (el reto final del módulo: dejar el producto operable en producción); se suma a `spec/01` a
`spec/04`, que siguen vigentes. Las personas dirigen, aprueban y comprueban: no programan.

- `/factory` corre la fábrica completa.
- `.claude/agents/`: architect, qa-unit, developer, observability, qa-style, costs, qa-e2e,
  security, guardrails, deploy, triage.
- `hooks/permissions.py`: cada agente escribe solo en sus carpetas; nadie lee `.env` y nadie publica sin
  `output/approved.txt`.
- `hooks/activity_log.py`: bitácora de cada herramienta; `scripts/pipeline.py` dibuja el pipeline.
- `verification/`: el código decide si un paso terminó bien, no el agente (unit, contract, qa, e2e, evaluate,
  load, production).

## Reglas

- El orquestador delega: nunca escribe en `product/` (corrige al agente, no su resultado).
- Todo bucle tiene tope: 2 rechazos del plan, 2 correcciones, 2 vueltas de qa-style y 2 ciclos de triage; después
  se escala a una persona.
- Una persona aprueba el plan antes de que se escriba código, y aprueba antes de publicar.
- Nunca leas `.env`.
- `product/` se versiona en el repositorio del curso: se publica una copia (`output/publish/`).
- Código en inglés; comentarios, docstrings, documentos y mensajes a las personas en español. Sin emojis.
  Es una excepción acordada a QA.md, que pide todo en inglés: no la reportes como incumplimiento.