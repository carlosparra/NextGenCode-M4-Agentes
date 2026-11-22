# Reporte de la fábrica (sesión 8: límite de tamaño de la respuesta)

**Estado: LISTA**

URL pública: https://hr-assistant-lhob.onrender.com

Repositorio privado: https://github.com/eagussot-dot/hr-assistant (rama `main`, último commit `9f7f13d`).

Confirmado con la prueba de humo de seis comprobaciones, que la persona corrió contra el servicio publicado (`4d0d4fa`) con `[OK] production`. La segunda comprueba que `/openapi.json` es público y describe `/ask` y `/health`; la sexta envía una CURP y un correo inventados y comprueba que la respuesta no los trae.

| Comprobación | Resultado |
|---|---|
| `GET /health` | 200 |
| `GET /openapi.json` sin clave: describe `/ask` y `/health` | `[OK]` |
| `POST /ask` sin clave | 401 |
| `POST /ask` con clave de cliente | 200 |
| La respuesta trae al empleado | `[OK]` |
| `POST /ask` con CURP y correo: la respuesta no los trae | `[OK]` |

Evidencia de la sesión 6 en los logs de Render (`LOG211126_3.txt`, 299 líneas, 00:39 a 00:49 UTC): dos eventos `agent_run` con `cost_usd` numérico (`4,9317e-05` y `5,0541e-05` USD, modelo `@cf/meta/llama-3.1-8b-instruct-fast`), dos `GET /openapi.json` con 200, tres `POST /ask` (dos 200 y un 401), 0 errores, 0 coincidencias de la CURP y el correo inventados y un evento `pii_masked` con `where=question`, `curp=1`, `email=1`.

Evidencia de la sesión 5 en los logs de Render (`LOG21126_1.txt`, 49 líneas, petición de las 23:50:19 UTC): 0 coincidencias de la CURP y del correo inventados; un evento `audit` con `action=pii_masked`, `where=question`, `curp=1`, `email=1` y sin el valor; y el argumento de la herramienta registrado como `[CURP]`. El log descargado es una ventana corta: contiene la petición con datos personales, no las otras dos de la prueba de humo.

Sesión 6: rechazos del plan 0 (máximo 2); correcciones del paso 5: 1 de 2 (código duplicado en las pruebas); vueltas de qa-style: 2 (`CAMBIOS` por documentación, luego `APROBADO`). Sesión 5: rechazos del plan 0 (máximo 2); correcciones del paso 5: 2 de 2; vueltas de qa-style: 2 (`CAMBIOS`, luego `APROBADO`). Sesión 4 (acumulado anterior): ciclos de triage 2 de 2, usados para el cambio de código del 502.

Pipeline dibujado: [output/pipeline.md](pipeline.md).

## Compuertas del producto (última corrida completa, commit `4d0d4fa`)

| Compuerta | Resultado |
|---|---|
| `unit` | 282 pruebas, cobertura 95,31 % |
| `contract` | 28 pruebas |
| `qa` | pylint 10.00/10 |
| `e2e` | 7 pruebas en Chromium |
| `evaluate` | calidad 100 %, ver tabla |
| `scripts/verify.py` (herramientas de la fábrica) | código 0 |
| Render | desplegó `4d0d4fa`; con `checksPass` solo despliega si el CI pasó |

Sesión 6: las pruebas de la prueba de humo (`tests/test_production.py`, 15 pruebas) pasaron a rojo antes de agregar la sexta comprobación. Comprobación de mutación de la sesión 5: con `PII_MASKING=false` fallan 4 de las 5 pruebas de contrato de la sesión 5, así que las pruebas detectan la falta de enmascarado.

## Tabla de `evaluate`: calidad y costo

Con el modelo simulado (compuerta `evaluate` de la fábrica; los tokens de esa corrida son 2740 y 2170):

| Configuración | Calidad | Costo (USD) |
|---|---|---|
| Línea base (`ROUTING=false`, sin ventana de historial) | 100 % | 0,001224 |
| Con palancas (configuración por omisión) | 100 % | 0,000169 |

Con el modelo real (`python -m verification evaluate --real`, 3 repeticiones, 0 errores; detalle en `output/evaluate-real.md`):

| Configuración | Calidad media | Peor calidad | Costo por corrida (USD) | Tokens de entrada | Errores |
| --- | --- | --- | --- | --- | --- |
| Baseline (`ROUTING=false`, sin ventana de historial) | 100 % | 100 % | 0,002842 | 6269 | 0 |
| Con palancas (configuración por omisión) | 100 % | 100 % | 0,000464 | 5938 | 0 |
| Con palancas y caché del gateway (TTL de 300 s) | 100 % | 100 % | 0,000153 | 6020 | 0 |

Medido con el modelo real (Workers AI vía AI Gateway), con `python -m verification evaluate
--real`: 8 preguntas con historial de relleno, 3 repeticiones por configuración, 0 errores. El
resultado completo está en `output/evaluate-real.md`. Una corrida son las 8 preguntas.

- **Ahorro:** las palancas bajan el costo un 83,7 % frente al baseline (de 0,002842 a 0,000464 USD
  por corrida, unos 0,000058 USD por pregunta) con la misma calidad. Con la caché del gateway baja
  un 94,6 % frente al baseline y un 67 % frente a las palancas solas.
- **De dónde viene:** los tokens de entrada solo bajan un 5,3 % (6269 a 5938), así que el ahorro
  viene del precio por token del modelo pequeño (el enrutamiento), no de la ventana de historial.
  Es una deducción de estos números; no se midió cada palanca por separado.
- **Caché:** el beneficio depende de que lleguen preguntas repetidas. En la medición la primera
  repetición paga y las otras dos salen casi gratis, lo cual favorece a la caché; con tráfico real
  el ahorro será menor y desconocido.
- **Salvedades:** el conjunto es pequeño (8 preguntas) y la calidad se decide por si la respuesta
  contiene ciertos textos, así que `100 %` no demuestra calidad en general. El costo se calcula con la tabla de precios del producto y se contrastó con el
  panel de AI Gateway (siguiente punto).
- **Confirmación en Cloudflare:** el panel de AI Gateway de las últimas 24 horas (captura
  `AIGatewayAnalitycs.jpeg`, tomada después de esta medición y antes de la prueba de carga)
  muestra 168 peticiones, 64,03k tokens, 0 errores y 34 aciertos de caché. El costo de
  `llama-3.3-70b` es 0,0085 USD, igual a las tres corridas del baseline (3 × 0,002842 =
  0,008526), y los 34 aciertos son coherentes con las repeticiones de la fila con caché. El
  total de 0,02 USD no es solo esta medición: el panel también lista modelos que el producto no
  usa (`gpt-oss-120b`, `qwen3.8-27b`), de pruebas anteriores.

## Prueba de carga

Herramienta: `python -m verification.load` con Locust (`uv run --with locust`), por escalones.

**A. Aplicación sola** (local, modelo simulado, sin límite de peticiones; 60 s por escalón;
`output/load-local.md`):

| Usuarios | Peticiones/s | p50 (ms) | p95 (ms) | Errores |
| --- | --- | --- | --- | --- |
| 1 | 3,11 | 15 | 18 | 0 |
| 5 | 15,46 | 13 | 18 | 0 |
| 10 | 31,29 | 11 | 17 | 0 |
| 20 | 62,40 | 9 | 16 | 0 |
| 50 | 154,12 | 17 | 38 | 0 |
| 100 | 207,41 | 160 | 320 | 0 |

El rendimiento crece en línea recta hasta 50 usuarios (unas 3 peticiones por segundo por usuario).
A 100 usuarios se aplana (207 por segundo en lugar de los 300 esperados) y el p95 pasa de 38 a
320 ms: ahí está la rodilla. No hubo errores y todos los escalones cumplen la meta de 2000 ms.
Salvedades: el modelo simulado responde al instante, así que esto mide solo el código de la
aplicación, y Locust corre en la misma máquina que el producto, por lo que no se sabe si la rodilla
es del servidor o del generador de carga.

**B. Render `free` con el modelo real** (pausas de 8 a 12 s para quedar bajo el límite por cliente,
y un escalón final que lo supera a propósito; `output/load-render.md`):

| Usuarios | Peticiones | 200 | 429 | p50 (ms) | p95 (ms) | Otros errores |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 9 | 9 | 0 | 980 | 1200 | 0 |
| 2 | 17 | 17 | 0 | 920 | 1100 | 0 |
| 3 | 25 | 25 | 0 | 890 | 1200 | 0 |
| 10 (supera el límite a propósito) | 156 | 49 | 107 | 870 | 1600 | 0 |

- Con 1 a 3 usuarios, todas las respuestas fueron 200 y el p95 quedó entre 1,1 y 1,2 s, dentro de
  la meta de 2000 ms. La latencia la domina el modelo y no cambió al pasar de 1 a 3 usuarios, que
  es una concurrencia pequeña.
- En el escalón que supera el límite, el servicio respondió 49 peticiones (p95 de 1,6 s, p99 de
  1,8 s) y rechazó 107 con `429`, sin ningún `502` ni otro error: el límite protege al modelo y el
  servicio no cae.
- Las 49 respuestas 200 en 30 s superan el límite de 30 por minuto porque la ventana es fija
  (ADR 0011) y el escalón cruzó un cambio de minuto: en ese borde puede pasar hasta el doble.
- No se pudo leer `/metrics` al final porque cuenta contra el mismo límite, que el último escalón
  había agotado; la herramienta ahora espera un minuto y reintenta.
- No se midió la capacidad de Render más allá del límite por cliente (con una sola clave el `429`
  llega antes de saturar el servicio), ni la CPU y la memoria del plan. Fueron unas 100 llamadas
  reales al modelo, unos 0,006 USD según el costo por pregunta de la medición de costos (estimado).
- Los resultados valen para el plan `free`; no se extrapolan a producción. La comparación con un
  plan de pago y dos instancias no se hizo (decisión de la persona) y queda como nota.

## Bitácora

1. Plan: `architect` actualizó `output/plan.md` y agregó los ADR 0010 a 0012.
2. Aprobación del plan: la persona aprobó sin comentarios.
3. Pruebas primero: `qa-unit` agregó 26 pruebas; `unit` falló como se esperaba (rojo).
4. Especialistas en paralelo: `security`, `deploy` y `qa-e2e`.
5. Compuertas, corrección 1: 4 avisos de pylint y `pylint` faltante en `product/requirements.txt`. Después pasaron las cinco compuertas.
6. Revisión de estilo: dos vueltas con `CAMBIOS` (README, docstrings), una revisión extra que llevó al inventario completo de docstrings Sphinx (0 funciones públicas sin formato según `ast`), y una última `APROBADO`.
7. Aprobación para publicar: la persona respondió «si». Se escribió `output/approved.txt`.
8. Publicación: la primera vez falló por falta de sesión de `gh`; la persona inició sesión y creó el repositorio privado desde el commit local.
9. CI: la etapa `style` falló con código 24 (pylint con opciones distintas a las de `verification/qa.py`); `deploy` igualó las opciones y el CI pasó.
10. Render: el primer arranque falló porque `API_KEYS` no tenía el formato `cliente:clave`; la persona lo corrigió en Render.
11. Prueba de humo, intento 1: `CERTIFICATE_VERIFY_FAILED` en la terminal de la persona (certificados de Windows); se resolvió con `truststore` en el comando, sin cambiar el código de la fábrica.
12. Prueba de humo, intentos 2 a 4: 502 en `POST /ask`. Triage ciclo 1: `persona` (credenciales o gateway, no visibles desde el repositorio).
13. Triage ciclo 2, cambio de código: el log del 502 solo decía `ModelUnavailable`. `qa-unit` escribió 11 pruebas en rojo, `security` hizo que `ModelUnavailable` conserve `cause` y `status_code` (sin URL, cuerpo, cabeceras ni secretos) y que el log los registre. Compuertas en verde, re-publicación aprobada por la persona (`ad3742f`).
14. Diagnóstico: el log mostró `cause=HTTPStatusError`, `status_code=401`: Cloudflare rechazaba la credencial del gateway. Era configuración de Cloudflare y de Render, no de código; la corrigió la persona.
15. Prueba de humo: tres `[OK]`. La página, sin embargo, respondía siempre «No pude completar la respuesta» (con código 200).
16. Defecto del agente con el modelo real, tres capas, cada una con pruebas en rojo primero (`qa-unit`), cambio de `developer`, compuertas verificadas por el supervisor y re-publicación aprobada por la persona:
    - `529e2f0`: el agente acepta la salida del modelo con valla de Markdown, texto alrededor o como objeto ya parseado; `GatewayModel` serializa un `content` que llegue como objeto; evento `invalid_model_output` (solo `reason`, `raw_type`, `raw_chars`).
    - `604cafe`: el prompt de sistema no decía qué herramientas existían, así que el modelo las inventaba. Ahora describe `get_employee` y `search_by_department` con sus argumentos; evento `invalid_tool_call` (solo `tool` y `arg_keys`). El log mostró entonces `tools: [get_employee, get_employee]` y una vuelta rechazada con `bad_shape`.
    - `7a39b1f`: el agente nunca agregaba la respuesta del propio modelo a la conversación, así que el modelo no veía su petición de herramienta y la repetía. Ahora se agrega el mensaje `assistant` y el resultado termina con una instrucción fija que pide `answer`.
17. Incidente de documentación: `architect` solo tiene `Write` y truncó `product/doc/architecture.md` (de 66 a 17 líneas). Se restauró desde git y se reaplicó el cambio verificando con `git diff` que solo cambió una línea.
18. Prueba de humo tras `7a39b1f`: tres `[OK]`, que no demostraban nada sobre la respuesta.
19. Prueba de humo corregida a petición de la persona (pruebas en rojo primero) y permisos de `architect` ampliados con `Edit`.
20. Prueba de humo corregida contra el servicio publicado: cuatro `[OK]`, la respuesta trae al empleado.
21. Pipeline: `scripts/pipeline.py` regeneró `output/pipeline.md`.
22. Sesión 5 (PII): se escribió `spec/05-pii.md` y `architect` planeó el enmascarado de CURP y correo (ADR 0013); la persona aprobó el plan con tres precisiones: `X-Request-ID` sin cambios, la CURP solo como palabra de 18 caracteres y el error 422 enmascarando solo CURP y correo.
23. `qa-unit` escribió las pruebas en rojo; `security` implementó `app/pii.py` y el enmascarado en entrada, respuesta y log (el logger enmascara los valores antes de serializar); `qa-e2e` agregó la prueba de la página.
24. Correcciones 1 y 2 de 2: dos pruebas con defectos propios (entrada de 2001 caracteres y un 422 con la CURP en un campo que FastAPI no devuelve) y un fixture del logger sin `masking`.
25. `qa-style`: vuelta 1 `CAMBIOS` (documentación desactualizada, logger inyectado mutado, constantes repetidas); vuelta 2 `APROBADO`.
26. Verificación propia del supervisor: el servidor de la fábrica ahora captura su salida y `verification/contract/test_contract_05.py` busca la CURP y el correo en la respuesta y en el log; la prueba de humo pasó a cinco comprobaciones.
27. Publicación aprobada por la persona (`73f0ff3`), prueba de humo con cinco `[OK]` y revisión del log de Render sin coincidencias.
28. Sesión 6 (costo y documentación): `spec/06-cost-and-docs.md` y plan de `architect` con ADR 0014, aprobado por la persona. Decisión: el agente recibe una función `cost_fn` y el costo se calcula una sola vez para `agent_run`, `/ask` y `/metrics`; la documentación OpenAPI no usa `response_model` para no alterar la respuesta, y el esquema `X-API-Key` usa `auto_error=False` para que el 401 siga igual.
29. `qa-unit` escribió 23 pruebas en rojo (14 fallaban por la razón correcta); `developer` implementó `cost_fn` y `app/api_docs.py`; `observability` documentó el campo y `security` el README y el checklist. Corrección 1 de 2: código duplicado entre pruebas, devuelto a `qa-unit`.
30. `qa-style`: vuelta 1 `CAMBIOS` (`api_docs.py` sin documentar en la arquitectura y el ADR; docstrings sin `:type` ni `:raises`), corregida por `architect` y `developer`; vuelta 2 `APROBADO`. El supervisor escribió las 5 pruebas de contrato nuevas y la sexta comprobación de la prueba de humo, y verificó cada compuerta por su cuenta.
31. Publicación aprobada por la persona (`4d0d4fa`), prueba de humo con seis `[OK]` y revisión del log de Render con `cost_usd` en `agent_run`. Dos logs anteriores (`LOG211126_2.txt` y el de despliegue) no servían: se descargaron antes de la prueba o eran del despliegue y no del servicio en marcha.
32. Medición con el modelo real: se agregó el modo `--real` a `evaluate` (pruebas en rojo primero; sin credenciales solo nombra las variables que faltan, nunca imprime valores; opción de certificados del sistema para el producto). La persona lo corrió con sus credenciales: las palancas bajan el costo un 83,7 % sin perder calidad (100 % en las tres configuraciones, 0 errores) y la caché del gateway un 94,6 %. Los tokens de entrada solo bajan un 5,3 %: el ahorro viene sobre todo del enrutamiento.
33. Captura del panel de AI Gateway (`AIGatewayAnalitycs.jpeg`, aportada por la persona): 168 peticiones, 0 errores y 34 aciertos de caché en 24 horas; el costo de `llama-3.3-70b` (0,0085 USD) coincide con las tres corridas del baseline. El panel incluye otros modelos que el producto no usa, de pruebas anteriores, así que su total (0,02 USD) no es el costo de la medición.
34. Prueba de carga: se escribió `verification/load.py` y `verification/locustfile.py` (pruebas en rojo primero) y se midió en local (modelo simulado, hasta 100 usuarios) y en Render con el modelo real. Tres fallos propios de la herramienta, corregidos en el camino: Locust escribe `N/A` en escalones sin peticiones terminadas; `truststore` choca con `gevent` en HTTPS y dejó los escalones en cero sin avisar (ahora se usa el contexto de certificados del sistema y se imprimen las excepciones de Locust); y `/metrics` cuenta contra el límite por cliente, así que la lectura final espera un minuto y reintenta. Resultado: el servicio responde `429` sin caerse al superar el límite, y con 1 a 3 usuarios el p95 es de 1,1 a 1,2 s.
35. Sesión 7 (prueba de humo automática): `spec/07-smoke-ci.md` y plan de `architect` (ADR 0015), aprobados por la persona. `qa-unit` escribió 25 pruebas en rojo (el script y el YAML como texto) y el supervisor 20 de paridad entre `product/scripts/smoke.py` y `verification/production.py`. Corrección 1 de 2 (dos avisos de pylint en las pruebas). `deploy` reescribió `scripts/smoke.py` (seis comprobaciones) y creó `smoke.yml` (manual y diario a las 13:17 UTC, permisos de solo lectura, clave por `env` desde un secreto). `security` actualizó el README y el checklist. `qa-style`: `APROBADO` en la vuelta 1. Compuertas: `unit` 307 pruebas (95,31 %), `contract` 28, `qa` 10,00, `e2e` 7, `verify.py` 114 pruebas.
36. Publicación aprobada por la persona (`5e4cd1d`). La primera corrida del flujo falló dos veces con código 2: la clave y la variable estaban en un Environment y no a nivel de repositorio, y el script no imprimió ningún valor. Corregida la configuración, la corrida manual terminó en `success` con seis `[OK]`.
37. Sesión 8 (límite de tamaño de la respuesta): `spec/08-answer-size.md` y plan de `architect` (ADR 0016), aprobados por la persona. Decisión: recortar y no reintentar ni reemplazar por el mensaje de fallo, y recortar DESPUÉS del enmascarado de PII (un corte antes dejaría media CURP en la respuesta). `qa-unit` escribió 40 casos en rojo y el supervisor 4 de contrato con el producto real (`MAX_ANSWER_CHARS=10`). Corrección 1 de 2: tres pruebas con datos mal armados (una CURP y un correo pegados a letras, que la especificación de la sesión 5 declara no detectables). `security` hizo el código y la documentación (`app/truncate.py`, `config.py`, `main.py`, `api_docs.py`, README y checklist). `qa-style`: `CAMBIOS` con 4 hallazgos menores (README, una prueba trivial, una aserción redundante y una constante repetida) y luego `APROBADO`. Compuertas: `unit` 345 pruebas (95,41 %), `contract` 32, `qa` 10,00, `e2e` 7, `verify.py` 115 pruebas.
38. Publicación aprobada por la persona (`9f7f13d`). La prueba de humo automática terminó en `success`; en el log de Render hay peticiones `/ask`, `pii_masked` solo con conteos, `cost_usd` en `agent_run` y cero `answer_truncated`.

## Hallazgos abiertos (no bloquean el cierre)

- `hooks/activity_log.py` no escribe de forma atómica: con agentes en paralelo dos escrituras simultáneas pueden dejar un fragmento suelto en `output/activity.jsonl` (pasó en la sesión 7: una línea de 7 caracteres). Mitigado al leer: `scripts/pipeline.py` descarta las líneas que no son JSON (prueba en `tests/test_activity_log.py`). La causa, la escritura no atómica en Windows, sigue abierta.
- `verification/production.py` no usa el almacén de certificados de Windows. En redes que interceptan TLS hay que pasar `truststore` en el comando. Hacerlo permanente toca el juez de la fábrica y lo decide la persona.
- `Dockerfile`: pip avisa de que corre como `root` al construir la imagen. Es solo un aviso; se quitaría con `--root-user-action=ignore`.
- RESUELTO a petición de la persona: la prueba de humo solo miraba el código HTTP. El defecto del agente lo demostró: la página devolvía «No pude completar la respuesta» y la prueba daba `[OK]`. Ahora `verification/production.py` añade una cuarta comprobación: la respuesta de `/ask` con clave debe nombrar a «Jorge Díaz» y no ser el mensaje de fallo (nunca imprime la respuesta). Con 9 pruebas en `tests/test_production.py`, escritas en rojo antes del cambio. La prueba de humo pasa a tener cuatro líneas `[OK]`; la corrida anterior (tres `[OK]`) es de antes de este cambio y hay que repetirla.
- El modelo simulado resolvía todo y escondió tres defectos que solo aparecieron con el modelo real. La compuerta `evaluate` de la fábrica sigue usando el modelo simulado; la medición con el modelo real es un paso manual (`evaluate --real`, necesita las credenciales de Cloudflare en la terminal de la persona).
- RESUELTO a petición de la persona: `architect` solo tenía `Write` y para cambios pequeños en `product/doc/` reescribía el archivo entero y podía truncarlo. Ahora `.claude/agents/architect.md` le da `Edit` y le exige leer el archivo completo y usar `Edit` en archivos que ya existen.
- Si 8B no basta, la alternativa es enrutar preguntas con herramientas al modelo grande (70B); es una decisión de costo.
- No se sabe qué cambio exacto hizo la persona en Cloudflare o Render para resolver el 401; no consta en la bitácora de la fábrica. Sí consta que `CF_API_TOKEN` tiene hoy los permisos `AI Gateway: Run`, `Workers AI: Edit` y `Workers AI: Read` (declarados por la persona). Con `AI Gateway: Run` el mismo token sirve para un gateway autenticado.
- `Workers AI: Edit` da más acceso del que la aplicación necesita (solo ejecuta modelos). Con `Workers AI: Read` y `AI Gateway: Run` bastaría; reducirlo es opcional.
- La URL usa el plan free de Render: el servicio duerme tras un rato sin tráfico y la primera petición tarda hasta un minuto.
