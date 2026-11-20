# ADR 0013: Detección de PII con expresiones regulares y validación de salidas

## Contexto

El producto ya está publicado (ADR 0010 a 0012). Un usuario puede escribir un correo, un teléfono o una tarjeta en
la pregunta o en el historial, y ese texto llegaba al modelo externo, al log de auditoría y a la traza. El modelo,
por su parte, podía devolver una respuesta vacía, demasiado larga o con una clave del sistema, y pedir herramientas
con argumentos arbitrarios. Los datos del directorio (nombre, `EMP-0001`, departamento, puesto, fecha, estado) son el
negocio y no deben ocultarse. Las pruebas exigen resultados exactos, incluso con 20 peticiones simultáneas.

## Decisión

- **PII:** `app/pii.py:redact_pii` es una función pura, sin red, estado ni log. Usa expresiones regulares y Luhn
  para cinco tipos de formato fijo (`card`, `curp`, `rfc`, `email`, `phone`, en ese orden, del más específico al más
  general) y cambia cada coincidencia por `[REDACTED:<kind>]`. Es idempotente.
- **Entrada:** `app/main.py:_screen_input` limpia la pregunta y todo el `history` antes de enrutar. Desde ahí solo
  existe el texto limpio. La petición no se rechaza.
- **Salida:** `app/guardrails.py:validate_answer` corre dentro de la función trazada `agent_run`
  (`Agent._checked_loop`) en este orden: secretos (`API_KEYS` y `CF_API_TOKEN` a `[REDACTED:secret]`), PII, respuesta
  vacía (mensaje fijo) y recorte a `MAX_ANSWER_CHARS` (2000 por omisión). Los secretos van primero para que una clave
  no se confunda con un teléfono ni quede cortada a la mitad.
- **Herramientas:** `validate_tool_args` aplica mínimo privilegio antes de tocar el directorio. Un argumento
  inválido devuelve un error legible para el agente, sin repetir el valor.
- **Inyección:** `detect_injection` compara una lista corta de frases con `fold_text`. Solo se audita.
- **Auditoría:** `app/security.py:SecurityAudit.record` recibe `request_id`, `client`, `stage`, `control` y `kinds`,
  nunca texto, y escribe en el log, en `/metrics` (`security`) y en un span de la traza. `/ask` agrega `redactions`.

## Consecuencias

- El valor detectado no puede llegar al log, a las métricas ni a la traza, porque ninguna firma lo recibe.
- Resultados deterministas y baratos: microsegundos por petición, sin tokens extra, fáciles de probar y de contar
  bajo concurrencia.
- Solo se detecta la PII con forma conocida. Hay falsos positivos (números de 10 dígitos, números que pasan Luhn) y
  falsos negativos (teléfonos con paréntesis, correos ofuscados, PII sin formato). Están listados en
  `doc/security.md`.
- La inyección no se bloquea: se confía en el alcance acotado del agente (ADR 0003) y en la validación de salida. Si
  el agente gana herramientas de escritura, esta decisión se revisa.
- El span `llm` sigue llevando la salida cruda del modelo; por eso en producción se exige `HIDE_OUTPUTS=true` con
  trazas (ADR 0012).
- Los campos nuevos (`redactions`, `security`) solo se agregan; ningún contrato anterior cambia.
