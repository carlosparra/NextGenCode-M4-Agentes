# 0013. Enmascarar CURP y correo en los bordes del servicio

## Contexto
Una persona puede escribir una CURP o un correo en la pregunta o en el historial. Ese dato llegaría al modelo, al gateway, a las trazas y al log, y volvería en la respuesta. El producto no necesita ese dato para responder, así que no debe salir del servidor.

## Decisión
Se enmascara en tres capas, con el módulo `pii.py` (funciones puras, sin red):
- Entrada: la pregunta y los mensajes `user` y `assistant` del historial, antes del agente. El largo se valida antes, con el texto original.
- Salida: el campo `answer`, antes de devolverse, aunque lo haya inventado el modelo.
- Log: `JsonLogger._serialize` enmascara los valores de cada campo, en profundidad (diccionarios, listas, tuplas, claves y el resultado de `default=str`), con `mask_deep` antes de `json.dumps`; así cubre todos los eventos, incluidos los campos anidados y los argumentos de la auditoría. No enmascara la línea ya serializada: con `ensure_ascii=True` un salto de línea o una letra con tilde pegados a un correo salen como `\n` o `ñ`, y un patrón sobre la línea se comería parte del escape y rompería el JSON. Con `PII_MASKING=false` el logger no enmascara.

La CURP se reemplaza por `[CURP]` y el correo por `[EMAIL]`; los marcadores no coinciden con los patrones, así que enmascarar de nuevo no cambia nada. Solo se revisa la estructura de la CURP; no se valida el dígito verificador. La CURP se detecta únicamente como palabra completa de 18 caracteres con la estructura oficial: si hay una letra o un dígito pegado justo antes o después, no se enmascara. Cada vez que se enmascara se emite un evento `audit` con `action=pii_masked`, `where` y los conteos, nunca el valor. La petición no se bloquea.

`PII_MASKING` vale `true` por omisión. Con `ENVIRONMENT=production`, `compliance.py` impide arrancar si vale `false` (ADR 0012), y la regla tiene su fila en `doc/compliance-checklist.md`.

## Consecuencias
- El modelo, el gateway, las trazas, el log y la respuesta no ven nunca una CURP ni un correo; la página sigue mostrando lo que la persona escribió.
- Límites aceptados: no se detectan variantes ofuscadas (espacios, guiones, «arroba», otro alfabeto, dato repartido entre mensajes) ni otros datos personales.
- Una CURP pegada a otras letras o dígitos no se enmascara (límite aceptado).
- Se puede enmascarar una CURP que no exista; se prefiere enmascarar de más.
- Enmascarar los valores de cada evento de log cuesta un poco de CPU; los patrones se compilan una vez y se prueban con 2000 caracteres.
- Una regla de detección nueva (por ejemplo RFC) exige cambiar `pii.py`, pruebas y la fila de la tabla de compliance.
