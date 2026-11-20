# Reporte de la fábrica: spec/05-security-hardening.md

**Estado:** LISTA

**URL pública:** https://hr-assistant-m1rp.onrender.com (commit `bdcce85` en `EvelyneFranco/hr-assistant`)

## Controles agregados

- **PII en la entrada** (`app/pii.py`): se ocultan correo, teléfono, tarjeta (solo si pasa Luhn), CURP y RFC en la
  pregunta y en todo el historial antes de enrutar. Los nombres y los `EMP-####` nunca se ocultan.
- **Validación de la salida** (`app/guardrails.py`, dentro de `agent_run`): primero secretos (`API_KEYS`), después PII,
  respuesta vacía con mensaje fijo y recorte a `MAX_ANSWER_CHARS` (2000 por omisión).
- **Mínimo privilegio en herramientas:** los argumentos se validan antes de llegar al directorio; el error al modelo no
  repite el valor; las herramientas desconocidas se registran como `unknown_tool` en `audit`, `security` y
  `tools_used`.
- **Inyección de prompt:** se detecta sin acentos ni mayúsculas, se audita y la petición sigue.
- **Auditoría** (`app/security.py`): evento `security` en el log, métrica y span de traza, sin recibir nunca el valor
  detectado.
- **API:** `/metrics` agrega `security` (pii, secret, output_invalid, tool_args, injection); `/ask` agrega
  `redactions`. Los campos anteriores no cambian.
- **Concurrencia:** prueba de 20 peticiones simultáneas con límite por cliente.
- **Documentación:** `doc/security.md`, ADR 0013, `architecture.md`, `compliance-checklist.md` y README.

## Correcciones y vueltas de QA

- Rechazos del plan: 0 de 2.
- Correcciones de compuertas: 1 de 2. Una prueba anterior (`test_metrics.py`) no incluía la llave `security` que pide
  el punto 7; la corrigió qa-unit, junto con avisos de pylint en las pruebas nuevas.
- Vueltas de qa-style: 2 de 2.
  - Vuelta 1, CAMBIOS: el README no explicaba cómo cargar `.env` (security); el nombre de herramienta inventado por el
    modelo llegaba al log sin validar (security en el código y qa-unit en la prueba).
  - Vuelta 2: APROBADO.
- Ciclos de humo: 2.
  - Ciclo 1: FAIL sin conectarse a Render porque `SMOKE_API_KEY` no llegó a la shell. Triage: `persona`.
  - Ciclo 2: OK.

## Tabla de evaluate

| Configuración | Calidad | Costo USD | Tokens de entrada |
|---|---|---|---|
| baseline | 100% | 0.000911 | 1647 |
| levers | 100% | 0.000121 | 1077 |

## Bitácora

1. Plan: architect actualizó `output/plan.md`.
2. Aprobación del plan: la persona respondió «si».
3. Pruebas primero: qa-unit agregó 25 pruebas, incluida la de concurrencia. `verification unit` dio ROJO, como se
   esperaba.
4. Implementación: security escribió los puntos 1 a 9 (`pii.py`, `guardrails.py` y `security.py`; cambios en
   `agent.py`, `main.py`, `config.py` y `metrics.py`).
5. Compuertas: `unit` falló 1 de 150 por una prueba desactualizada. qa-unit la corrigió (corrección 1) y después
   pasaron `unit` (150), `contract` (22), `qa` (10/10), `e2e` (5) y `evaluate`.
6. Documentación: architect escribió `doc/security.md` y el ADR 0013, y actualizó `architecture.md`.
7. qa-style vuelta 1: CAMBIOS. Los corrigieron security y qa-unit. Las compuertas pasaron de nuevo (`unit` 151) y la
   vuelta 2 dio APROBADO.
8. Aprobación para publicar: la persona respondió «si» y se escribió `output/approved.txt`.
9. Publicación: `publish.py` dio OK, con el commit `bdcce85` en main. La persona confirmó el CI en verde y Render en
   Live.
10. Humo:
    - Ciclo 1: FAIL porque faltaba `SMOKE_API_KEY` en la shell. Triage: `persona`, y la persona lo resolvió.
    - Ciclo 2: OK en `/health` (200), `/ask` sin clave (401) y `/ask` con clave (200).
11. Pipeline: `output/pipeline.md` con 27 pasos.

Pendiente para la persona: rotar la clave de humo, que quedó visible en la conversación al definirla con `!`.

Pipeline: [output/pipeline.md](pipeline.md)
