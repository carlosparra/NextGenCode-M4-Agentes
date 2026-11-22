persona

Que fallo: POST /ask con clave valida devuelve 502 (esperado 200). /health y el 401 sin clave pasan, asi que el servicio arranca, las variables CF_ACCOUNT_ID y CF_API_TOKEN existen (si no, config.py no habria dejado arrancar con MODEL_PROVIDER=gateway) y la validacion de claves funciona. El 502 sale solo de ModelUnavailable en main.py, que GatewayModel.generate lanza ante cualquier httpx.HTTPError (incluye respuestas 4xx/5xx por raise_for_status, timeout y errores de red) o ante un cuerpo sin choices/usage (KeyError, IndexError, TypeError, ValueError). Un JSON invalido del modelo no causa 502: agent.py lo reintenta con retroalimentacion.

Por que no es security ni deploy: el codigo y el render.yaml son coherentes con README y .env.example, y el CI paso. La URL (gateway.ai.cloudflare.com/v1/{cuenta}/{gateway}/workers-ai/v1/chat/completions), la cabecera Authorization: Bearer y el cuerpo (model, messages, max_tokens, temperature) tienen la forma esperada de Workers AI. Lo que no se puede ver desde el repositorio es el valor de los secretos ni la configuracion de la cuenta de Cloudflare, que solo la persona ve. Ningun agente puede ni debe tocarlos.

Causas, de mas a menos probable, y que dato la confirma:

1. Token de Cloudflare invalido o sin permiso (HTTP 401/403 desde el gateway). Token mal pegado (espacios o salto de linea), expirado, o creado sin el permiso "Workers AI" (Read/Edit) sobre esa cuenta. Confirma: en Render > Logs, la linea de error de /ask dice error_type=HTTPStatusError; en Cloudflare > AI > AI Gateway > (tu gateway) > Logs, la peticion aparece con estado 401 o 403, o no aparece. Revisar tambien en Cloudflare > My Profile > API Tokens que el token este activo y con el permiso de Workers AI.

2. Gateway inexistente o con otro id (HTTP 404). El codigo usa CF_GATEWAY_ID=default porque render.yaml no define esa variable. Si el gateway "default" no existe en la cuenta, o el creado tiene otro nombre, falla. Confirma: error_type=HTTPStatusError en Render y en Cloudflare > AI Gateway la lista de gateways no incluye "default" (ningun log de peticion). Solucion de la persona: crear el gateway con ese id o agregar CF_GATEWAY_ID con el id real en Render > Environment.

3. Gateway autenticado (Authenticated Gateway activado) (HTTP 401). Ese modo exige la cabecera cf-aig-authorization, que el codigo no envia. Confirma: en Cloudflare > AI Gateway > Settings, "Authenticated Gateway" esta en On, y el log del gateway o la respuesta muestran 401 por falta de autenticacion. Si es asi, la persona lo desactiva; si se quisiera mantener activo, seria un cambio de codigo (security o deploy) y habria que reabrir el triage.

4. CF_ACCOUNT_ID incorrecto (HTTP 404/403). Se uso otro id (por ejemplo el de una zona, no el de la cuenta) o tiene espacios. Confirma: error_type=HTTPStatusError en Render y ninguna peticion en el log del gateway. Si tuviera un espacio o salto de linea, httpx podria fallar con InvalidURL y daria 500 en vez de 502; un 502 apunta mas a un estado HTTP que a esto.

5. Modelo no disponible en la cuenta, o cuenta sin Workers AI habilitado o sin cupo (HTTP 400/403/429). Los modelos por omision son @cf/meta/llama-3.1-8b-instruct-fast y @cf/meta/llama-3.3-70b-instruct-fp8-fast. Confirma: el log del gateway muestra la peticion con el modelo y un 4xx o 429 con el motivo (modelo no encontrado, limite diario superado). Revisar Cloudflare > AI > Workers AI.

6. Falla de red o timeout desde Render (plan free, 30 s de tope en REQUEST_TIMEOUT_SECONDS). Arranque en frio o lentitud del gateway. Confirma: en Render el error_type es ConnectTimeout, ReadTimeout o ConnectError, y en el gateway no hay peticion, o hay una con latencia cercana a 30 s. Repetir la prueba una segunda vez con el servicio ya despierto.

7. Respuesta 200 con forma distinta a la esperada (KeyError "usage", IndexError, TypeError o ValueError). Workers AI compatible con OpenAI normalmente devuelve choices y usage, pero si faltara usage, el codigo lo trata como falla. Confirma: error_type=KeyError (o IndexError/TypeError/JSONDecodeError) en Render, y en el log del gateway la peticion con 200. Este es el unico caso que pasaria a deploy/security como cambio de codigo.

Que tiene que hacer la persona, en este orden:
a) Render > hr-assistant > Logs: buscar la linea de nivel error de /ask posterior a la prueba y anotar solo el valor de error_type (no copiar ningun secreto). Esto distingue las causas 1 a 5 (HTTPStatusError), 6 (ConnectTimeout, ReadTimeout, ConnectError) y 7 (KeyError, etc.).
b) Cloudflare > AI > AI Gateway: confirmar que existe un gateway con id "default" (o el id real), que "Authenticated Gateway" esta apagado, y abrir sus Logs para ver el estado HTTP de la peticion de la prueba.
c) Cloudflare > My Profile > API Tokens: comprobar que el token esta activo y tiene permiso de Workers AI sobre la cuenta. Si hay duda, crear uno nuevo y reescribirlo en Render > Environment > CF_API_TOKEN.
d) Render > Environment: revisar que CF_ACCOUNT_ID y CF_API_TOKEN no tengan espacios ni saltos de linea al inicio o al final, y agregar CF_GATEWAY_ID si el gateway no se llama "default". Guardar y dejar que Render redespliegue.
e) Repetir la prueba de humo. Si el error_type del paso a) fuera KeyError, IndexError o TypeError con un 200 en el gateway, devolver el triage con ese dato para reasignarlo como cambio de codigo.

Mejora posible (no urgente, sin reasignar ahora): el log del 502 solo guarda el nombre de la excepcion, no el codigo HTTP, lo que obliga a mirar Cloudflare para distinguir 401, 404 y 429. Registrar el status_code ayudaria a diagnosticar la proxima vez.
