# 0004. Log JSON con request_id y sin texto del usuario

## Contexto
Hay que responder qué pasó con una petición concreta, y las preguntas de RH pueden contener datos personales.

## Decisión
Cada petición lleva un `request_id` (el de `X-Request-ID` o un UUID) guardado en una variable de contexto. Todo evento se escribe como una línea JSON en la salida estándar con `ts`, `service`, `event` y `request_id`. Los eventos (`request`, `agent_run`, `audit`, `error`) se arman con campos fijos: longitudes y conteos, nunca el texto de la pregunta ni de la respuesta. La hora sale de un reloj inyectado.

## Consecuencias
- Con el `request_id` se reconstruye una petición completa con solo filtrar el log.
- El log no filtra datos personales, pero tampoco sirve para reproducir el texto de una pregunta.
- Las pruebas son deterministas porque el reloj es falso.
- Todo evento nuevo debe pasar por el logger y respetar la regla de no incluir texto.
