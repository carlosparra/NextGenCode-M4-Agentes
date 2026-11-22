# Sesión 5 · PII: no mostrar de nuevo la CURP ni el correo

Parte del producto de las sesiones 1 a 4. Agrega una sola regla: la **CURP** y el **correo electrónico** que escribe una
persona no vuelven a aparecer en ninguna salida del producto. Se enmascaran; no se bloquea la petición. No se
detecta ningún otro dato personal.

## Lo que debe hacer

1. **Qué se detecta** (módulo `app/pii.py`, funciones puras, sin red):
   - **CURP (México):** 18 caracteres seguidos, sin importar mayúsculas o minúsculas. Cuatro letras (la segunda es una
     vocal o `X`), seis dígitos de fecha `AAMMDD` con mes `01` a `12` y día `01` a `31`, una letra `H`, `M` o `X`, la
     clave de estado (`AS`, `BC`, `BS`, `CC`, `CL`, `CM`, `CS`, `CH`, `DF`, `DG`, `GT`, `GR`, `HG`, `JC`, `MC`, `MN`,
     `MS`, `NT`, `NL`, `OC`, `PL`, `QT`, `QR`, `SP`, `SL`, `SR`, `TC`, `TS`, `TL`, `VZ`, `YN`, `ZS` o `NE`), tres
     consonantes, un carácter alfanumérico y un dígito. Solo se revisa la estructura; **no** se valida el dígito
     verificador. No se detecta si lleva espacios o guiones. Solo se detecta como palabra completa de 18 caracteres: si hay
     una letra o un dígito pegado justo antes o justo después, no es una CURP y no se enmascara.
   - **Correo electrónico:** `usuario@dominio.tld`. El usuario admite letras, dígitos y `. _ % + -`; el dominio admite
     letras, dígitos, puntos y guiones, y termina en un punto y de 2 a 24 letras.
   - No se enmascara nada que no cumpla esas formas: `EMP-0004`, los nombres, los departamentos y las fechas del
     directorio quedan intactos.
2. **Cómo se enmascara.** La CURP se reemplaza por `[CURP]` y el correo por `[EMAIL]`. Enmascarar un texto ya
   enmascarado no lo cambia. La petición se atiende con normalidad.
3. **Entrada.** En `POST /ask`, la pregunta y todos los mensajes del historial (`user` y `assistant`) se enmascaran
   **antes** de llegar al agente. El largo de la pregunta se valida antes, con el texto original. El modelo, el
   gateway y las trazas nunca reciben una CURP ni un correo.
4. **Respuesta.** El campo `answer` se enmascara antes de devolverse, aunque el modelo lo haya inventado.
5. **Log.** Ninguna línea del log contiene una CURP ni un correo. `JsonLogger` enmascara los valores de cada campo
   **antes** de serializar la línea, así que cubre todos los eventos y todos sus campos, incluidos los anidados y los
   argumentos de la auditoría. No enmascara la línea ya serializada: un `\n` o un `ñ` pegados a un correo harían
   que el patrón rompiera el JSON.
6. **Errores de validación.** Si un error `422` de validación devuelve el valor recibido, las CURP y los correos que
   contenga salen enmascarados. Solo eso: el resto del error no se altera. Si no devuelve el valor, no se cambia nada.
7. **Auditoría.** Cada vez que se enmascara algo se emite un evento `audit` con `action=pii_masked`, `where`
   (`question`, `history` o `answer`) y el número de CURP y de correos enmascarados. Es un evento por cada `where`, con los conteos sumados.
   **Nunca el valor.**
8. **Configuración.** `PII_MASKING` vale `true` por omisión. Con `ENVIRONMENT=production` el producto **se niega a
   arrancar** si vale `false`. Con `false` (solo desarrollo) se apagan las tres capas: la entrada, la
   respuesta y el log. `doc/compliance-checklist.md` tiene una fila nueva para esta regla.

## Lo que no cambia

- La forma de la respuesta de `POST /ask`: no hay campos nuevos.
- Las herramientas y los datos del directorio.
- La página web: sigue mostrando a la persona lo que ella misma escribió; el enmascarado ocurre en el servidor.

## Límites aceptados

- No se detectan las variantes ofuscadas: una CURP con espacios o guiones, «nombre arroba dominio punto com»,
  caracteres de otro alfabeto que se parecen a los latinos, ni un dato repartido entre dos mensajes.
- Como no se valida el dígito verificador, se puede enmascarar una CURP que no exista. Se prefiere enmascarar de más.
- Una CURP pegada a otras letras o dígitos (una palabra de más de 18 caracteres) no se detecta.

## Configuración nueva

| Variable | Por omisión | Para qué |
| --- | --- | --- |
| `PII_MASKING` | `true` | Enmascara CURP y correo en entradas, respuestas y logs; en producción no puede ser `false` |

## Pruebas

- **`qa-unit`**, antes del código:
  - Detección de la CURP: válida en mayúsculas y en minúsculas, dentro de una frase y varias en un texto. No se
    detecta con mes `13`, con estado inexistente ni con 17 caracteres.
  - Detección del correo: simple, con `+`, con subdominios y varios en un texto. No se detecta `@juan` ni un texto
    sin dominio.
  - Falsos positivos (`EMP-0004`, «Jorge Díaz», departamentos y fechas), idempotencia y una entrada de 2000
    caracteres sin lentitud.
  - Flujo completo con el modelo simulado: el modelo no recibe el dato, la respuesta no lo contiene y el log no lo
    contiene, ni siquiera en la auditoría. Historial con PII en mensajes `user` y `assistant`.
  - Compliance: producción no arranca con `PII_MASKING=false`.
  - Una CURP con una letra o un dígito pegado antes o después no se detecta; un correo cuyo dominio termina en 25
    letras o más no se detecta.
  - Una línea de log con caracteres que no son ASCII sigue siendo JSON válido y con los datos enmascarados.
  - Un `422` con una CURP o un correo en el valor recibido sale con solo esos datos enmascarados.
- **`qa-e2e`**: en la página, una pregunta con una CURP y un correo no los muestra en la respuesta.

## Cómo se comprueba

- `verification unit`, `contract`, `qa`, `e2e` y `evaluate`, como en la sesión 4.
- `verification contract`: el servidor de la fábrica captura su propia salida, y una prueba nueva envía una CURP y un
  correo de prueba y comprueba que **no aparecen ni en la respuesta ni en el log capturado**.
- `uv run python -m verification production <url>`: la prueba de humo tiene una quinta comprobación. Envía una CURP
  inventada y un correo `@example.com` y comprueba que la respuesta no los trae.
- Una persona aprueba la publicación. Después de publicar, se descargan los logs de Render y se buscan los valores de
  prueba: debe haber cero coincidencias y deben aparecer `[CURP]` o `[EMAIL]`.
