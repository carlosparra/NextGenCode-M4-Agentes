# Sesión 8 · Límite de tamaño de la respuesta

Parte del producto de las sesiones 1 a 7. Hoy la respuesta del modelo solo está acotada por **tokens** (`MODEL_MAX_TOKENS`,
300), un tope que depende de que el gateway lo respete. El producto nunca comprueba el **texto** de `answer`. Esta sesión
agrega esa comprobación en el servidor: la respuesta que sale de `POST /ask` nunca pasa de un número de caracteres.

## Lo que debe hacer

1. **Límite configurable.** `MAX_ANSWER_CHARS`, por omisión **1500** caracteres (300 tokens caben holgadamente en ese
   tamaño). Debe ser un entero positivo; si no, el producto no arranca y el error nombra la variable, como las demás.
2. **Qué pasa al pasarse.** Si el campo `answer` supera el límite, se **recorta** a exactamente el límite: los primeros
   `MAX_ANSWER_CHARS - 1` caracteres y un `…` (un solo carácter) al final. La petición se atiende con normalidad
   (`200`); no se reintenta ni se reemplaza por el mensaje de fallo. Una respuesta dentro del límite sale intacta.
3. **El recorte va después del enmascarado de PII.** Primero se enmascaran la CURP y el correo y después se recorta. Al
   revés, un corte en medio de una CURP la dejaría incompleta (y ya no coincidiría con el patrón), y parte del dato
   saldría en la respuesta.
4. **Aviso.** Cada recorte emite un evento `answer_truncated` con solo números: `original_chars` y `limit_chars`. Nunca
   el texto. Sin recorte no se emite nada.
5. **Documentación.** La descripción de `answer` en `/openapi.json` dice el límite por omisión; no se agrega una
   restricción al esquema (el límite es configurable). `README.md`, `.env.example`, `doc/architecture.md` y
   `doc/compliance-checklist.md` lo reflejan, y un ADR nuevo registra la decisión.
6. **Funciones puras.** El recorte vive en un módulo propio de `app/` (sin red ni estado) para poder probarlo solo.

## Lo que no cambia

- La forma de la respuesta de `POST /ask`: los mismos diez campos; `/metrics`; el costo y los tokens.
- El enmascarado de PII, el límite de la pregunta (`MAX_QUESTION_CHARS`) y el tope de tokens del modelo.
- El bucle del agente: no se reintenta por tamaño.
- La prueba de humo y `evaluate`: las respuestas normales son mucho más cortas que el límite.

## Límites aceptados

- Recortar puede cortar una respuesta válida y larga. Se prefiere eso a devolver un texto sin límite; el evento
  `answer_truncated` permite verlo en los logs.
- No se valida el contenido de la respuesta más allá de su tamaño y del enmascarado de PII.
- No se limita el tamaño de los mensajes del historial de entrada. Es otro asunto (entrada, no respuesta) y queda fuera.

## Pruebas

- **`qa-unit`**, antes del código:
  - Función de recorte: dentro del límite no cambia; justo en el límite no cambia; un carácter más recorta a exactamente
    el límite y termina en `…`; un texto vacío no cambia; un límite de 1 devuelve solo `…`; no rompe caracteres con
    acento ni `ñ`.
  - `POST /ask` con un modelo simulado que contesta un texto muy largo: `answer` mide el límite, termina en `…`, el
    resto de la respuesta (diez campos, tokens, costo) no cambia y el estado es `200`.
  - Una CURP o un correo que cruzan el punto de corte no salen ni siquiera en parte (se enmascara antes de recortar).
  - El evento `answer_truncated` trae solo `original_chars` y `limit_chars` y el log no contiene el texto recortado.
  - Con una respuesta corta no se emite el evento.
  - Configuración: por omisión 1500; `MAX_ANSWER_CHARS` válido se respeta; `0`, negativo o no numérico impiden arrancar y
    el error nombra la variable.
  - El esquema OpenAPI sigue teniendo las mismas propiedades en `AskResponse` y su descripción de `answer` menciona el
    límite.
- **`qa-e2e`**: ninguna; la página muestra lo que devuelve la API.

## Cómo se comprueba

- `verification unit`, `contract`, `qa`, `e2e` y `evaluate`, y `scripts/verify.py`, como en la sesión 7.
- `verification contract`: una prueba nueva arranca el producto con `MAX_ANSWER_CHARS` muy pequeño y comprueba que la
  respuesta real mide el límite, termina en `…` y que el log capturado trae el evento `answer_truncated` sin el texto.
- Una persona aprueba la publicación. Después, la prueba de humo sigue en seis `[OK]` (las respuestas normales no se
  recortan) y en los logs de Render no aparece `answer_truncated` con tráfico normal.
