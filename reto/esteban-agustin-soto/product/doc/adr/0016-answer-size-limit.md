# 0016. Límite de tamaño de la respuesta en caracteres

## Contexto
Hoy la respuesta del modelo solo está acotada por tokens (`MODEL_MAX_TOKENS`, 300), un tope que depende de que el gateway lo respete. El producto nunca comprueba el texto de `answer`: un modelo que ignore el tope, o un gateway que no lo aplique, podría devolver un texto sin límite al personal de RH, al log y a las métricas. Además, la respuesta pasa por el enmascarado de PII (ADR 0013), y un corte hecho antes podría dejar una CURP incompleta que ya no coincide con el patrón.

## Decisión
- Un límite en caracteres, `MAX_ANSWER_CHARS`, por omisión 1500 (300 tokens caben holgadamente). Debe ser un entero positivo; si no, el producto no arranca y el error nombra la variable. Complementa al tope de tokens, no lo reemplaza: el tope de tokens limita el costo y el de caracteres limita lo que el servidor devuelve, sin depender del gateway.
- Si `answer` lo supera, se recorta a exactamente el límite: los primeros `MAX_ANSWER_CHARS - 1` caracteres y un `…` al final. La petición sigue en `200`. No se reintenta, porque otra llamada cuesta dinero y puede volver a pasarse; tampoco se reemplaza por el mensaje de fallo, porque se perdería una respuesta que en su mayor parte es válida.
- El recorte va después del enmascarado de PII. Primero se enmascaran la CURP y el correo y después se recorta; al revés, un corte en medio de una CURP la dejaría incompleta, ya no coincidiría con el patrón y parte del dato saldría en la respuesta.
- El recorte vive en `app/truncate.py`, con funciones puras sin red ni estado.
- Cada recorte emite el evento `answer_truncated` con solo números, `original_chars` y `limit_chars`, nunca el texto: el log no debe volver a guardar lo que se quiso acotar. Sin recorte no se emite nada.
- No entra en `compliance.py`: esa verificación impide arrancar con una configuración insegura en producción, y este límite siempre tiene un valor válido (por omisión 1500, nunca apagado, porque cero o negativo no arrancan). Su validación ya está en `config.py`.
- La descripción de `answer` en `/openapi.json` menciona el límite por omisión, sin agregar una restricción al esquema porque el límite es configurable.

## Consecuencias
- La respuesta de `POST /ask` nunca pasa de `MAX_ANSWER_CHARS`, tenga o no el modelo un tope de tokens efectivo; la forma de la respuesta, el costo y los tokens no cambian.
- Recortar puede cortar una respuesta válida y larga; se prefiere eso a devolver un texto sin límite, y `answer_truncated` permite verlo en los logs (con tráfico normal no debe aparecer).
- El texto recortado se pierde y no queda en el log, por diseño; solo se sabe cuántos caracteres tenía y cuál era el límite.
- No se cubre el tamaño de los mensajes del historial de entrada: es entrada, no respuesta, y queda fuera de esta sesión.
- Tampoco se valida el contenido de la respuesta más allá de su tamaño y del enmascarado de PII.
