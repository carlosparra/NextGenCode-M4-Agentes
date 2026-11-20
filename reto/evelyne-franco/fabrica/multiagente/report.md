# Reporte de la fábrica: spec 06 (multi-agente)

**Estado: LISTA**

**URL pública:** https://hr-assistant-m1rp.onrender.com

## Agentes agregados

Cada petición a `/ask` pasa por cuatro agentes, en este orden:

1. **guard** (`app/guard.py`): filtra la PII y la inyección de la pregunta.
2. **supervisor** (`app/supervisor.py`): elige el especialista. Primero aplica reglas en código: `rule:employee`, `rule:department` y `rule:policy`. Solo si ninguna aplica, hace una llamada a `MODEL_SMALL` (`model`); si esa respuesta no sirve, la ruta es `model_invalid`. Los tokens y el costo de esa llamada se suman a la respuesta.
3. **Un solo especialista**, con un registro de herramientas propio:
   - `directory` usa `get_employee` y `search_by_department`.
   - `policy`, que es nuevo, usa `search_policy` sobre `data/policies.json`. Con `rule:policy`, la política se consulta en código antes de llamar al modelo.
4. **reviewer** (`app/reviewer.py`): reemplaza los ids inventados y los números que no aparecen en la política, y lo registra como el control `ungrounded`.

Campos nuevos:
- En `/ask`: `specialist`, `agents` y `supervisor_route`.
- En `/metrics`: `specialists` y `supervisor`.

## Traza raíz

Cada petición crea un solo run `request` en LangSmith. Dentro van `agent.guard`, `agent.supervisor`, `agent.directory` o `agent.policy`, y `agent.reviewer`. Todos los runs llevan `request_id` y `client`.

Los metadatos `specialist` y `supervisor_route` se agregan al run raíz después de que decide el supervisor, con `Tracer.annotate`. Las etapas que son código no reciben texto.

Dentro del especialista, el run `agent_run` y el run `llm` sí llevan texto. Por eso `HIDE_INPUTS` y `HIDE_OUTPUTS` tienen que seguir encendidos en producción (lo documentan el ADR 0015 y `doc/security.md`).

## Correcciones y vueltas de QA

- **Correcciones del paso 6: 0 de 2.**
  - El primer intento se detuvo en `e2e` porque la sesión usaba el entorno de Python de la sesión 1, que no tiene Playwright. La persona arregló el entorno y en la segunda corrida pasaron las cinco compuertas.
  - Antes de las compuertas, qa-unit corrigió una prueba propia que contradecía la spec: el conjunto de llaves de `/metrics` en `test_security.py`. En el mismo cambio quitó los hallazgos de pylint en las pruebas.
- **Vueltas de qa-style: 1 de 2.** El resultado fue APROBADO.
- **Ciclos de humo y triage: 0 de 2.**
  - El primer intento no corrió porque `SMOKE_API_KEY` no estaba en el entorno de la sesión.
  - Cuando la persona la definió, la prueba pasó.

## Compuertas

| Compuerta | Resultado |
| --- | --- |
| unit | OK: 176 pruebas, cobertura 96.67 % |
| contract | OK: 28 pruebas |
| qa | OK: pylint 10.00/10 |
| e2e | OK: 5 pruebas |
| evaluate | OK |
| production | OK: `/health` 200, `/ask` sin clave 401, `/ask` con clave 200 |

### Tabla de evaluate

| Configuración | Calidad | Costo (USD) | Tokens de entrada |
| --- | --- | --- | --- |
| baseline | 100 % | 0.000914 | 1708 |
| levers | 100 % | 0.000125 | 1138 |

## Riesgos documentados

- El mínimo privilegio se aplica en el registro de herramientas, no en el acceso a los datos: el especialista `policy` también recibe el `Directory`, aunque solo lo usa para validar argumentos.
- Ninguna prueba comprueba que el supervisor reciba la pregunta sin PII. Hoy eso depende solo del orden de `RequestPipeline`.
- El texto de política con el que el reviewer reemplaza una respuesta no vuelve a pasar por `screen_answer`; solo se recorta.

## Bitácora

1. **Plan:** architect escribió `output/plan.md`.
2. **Aprobación del plan:** la persona aprobó en el primer intento. Entraron tres decisiones:
   - El escenario usa «30 días».
   - Los spans `tool_args` quedan dentro del especialista.
   - Si falla el supervisor, la respuesta es 502.
3. **Pruebas primero:** qa-unit agregó 25 pruebas y actualizó 3. `unit` dio rojo, como se esperaba: faltaba `app.policies`.
4. **Agentes:** developer escribió `policies`, `prompts`, `supervisor`, `reviewer`, `guard` y `orchestrator`, y agregó el log y las métricas. Quedaron 6 pruebas en rojo: 5 de la traza y 1 prueba mal escrita.
5. **Traza raíz:** observability agregó el run `request` y los runs `agent.*` con `Tracer.annotate`, y actualizó `README.md`. En paralelo, qa-unit corrigió su prueba de llaves y el estilo de las pruebas.
6. **Compuertas:** el primer intento se detuvo en `e2e` por el entorno. Después del arreglo de la persona pasaron unit, contract, qa, e2e y evaluate.
7. **Documentación:** architect escribió `doc/architecture.md`, `doc/adr/0014-rule-first-supervisor-and-separate-specialists.md`, `doc/adr/0015-root-trace-per-request.md` y `doc/security.md`.
8. **Revisión:** qa-style dio APROBADO en la vuelta 1.
9. **Aprobación para publicar:** la persona dijo «si». Se escribió `output/approved.txt`.
10. **Publicación:** `scripts/publish.py` hizo el commit `6b26172` y el push a `main`. El CI pasó y Render quedó Live.
11. **Humo:**
    - El primer intento no corrió porque faltaba `SMOKE_API_KEY`.
    - La persona dijo que la prueba había pasado en su terminal, pero no pegó la salida. No se tomó como veredicto.
    - Cuando la persona definió la clave en la sesión, la prueba corrió aquí y dio `[OK] production`.
12. **Pipeline y reporte:** `scripts/pipeline.py` dibujó 19 pasos.

Pipeline: [output/pipeline.md](pipeline.md)
