# Reto · Seguridad reforzada: PII, validación de salidas y concurrencia

Parte del producto de la sesión 4, que ya está publicado en Render. Agrega lo que pide la rúbrica del reto y todavía
no existe:
- Detección de información sensible (PII) en preguntas y respuestas.
- Validación de las salidas del modelo y de los argumentos de las herramientas.
- Detección de intentos de inyección de instrucciones.
- Evidencia de que el producto atiende peticiones concurrentes.

**Nada de lo que ya funciona puede romperse.** Las pruebas y verificaciones de las sesiones 1 a 4 siguen pasando.

## Qué datos son legítimos y cuáles son PII

Los datos del directorio son el negocio del producto y **no se ocultan**: el nombre, el `id` (`EMP-0001`), el
departamento, el puesto, la fecha de ingreso y el estado. Las pruebas de contrato esperan nombres como «Jorge Díaz»
en las respuestas.

PII es lo que el directorio **no** tiene y nunca debería viajar al modelo, al log ni a la traza:

| Tipo (`kind`) | Qué detecta | Ejemplo |
| --- | --- | --- |
| `email` | Correo electrónico | `ana@empresa.com` |
| `phone` | Teléfono de 10 dígitos, con o sin `+52`, espacios o guiones | `55 1234 5678` |
| `card` | Tarjeta de 13 a 19 dígitos **que pasa el algoritmo de Luhn** | `4111 1111 1111 1111` |
| `curp` | CURP mexicana (18 caracteres con el formato oficial) | `GODE561231MDFRRS09` |
| `rfc` | RFC de persona física (13 caracteres) | `GODE561231AB1` |

Cada coincidencia se reemplaza por `[REDACTED:<kind>]`. La detección vive en un solo módulo, `app/pii.py`, con una
función pura que recibe un texto y devuelve el texto limpio y la lista de tipos encontrados. No usa red ni modelos:
solo expresiones regulares y Luhn, para que sea rápida, determinista y fácil de probar.

## Lo que debe hacer

1. **PII en la pregunta (entrada).**
   - Antes de enrutar y de llamar al agente, la pregunta y el `history` pasan por `app/pii.py`.
   - El modelo, el log, la auditoría y la traza **solo ven el texto limpio**. El valor original nunca se escribe.
   - La petición **no se rechaza**: el producto responde con el texto limpio.
2. **PII en la respuesta (salida).** La respuesta final del agente también pasa por `app/pii.py` antes de devolverse.
3. **Validación de la salida.** Después de limpiar la PII, la respuesta:
   - Debe ser texto no vacío. Si viene vacía, se devuelve el mensaje fijo «No pude generar una respuesta segura.».
   - Se recorta a `MAX_ANSWER_CHARS` caracteres.
   - **Nunca contiene una clave de `API_KEYS` ni `CF_API_TOKEN`.** Si aparece alguna, se reemplaza por
     `[REDACTED:secret]`.
4. **Validación de los argumentos de las herramientas** (mínimo privilegio).
   - `get_employee` solo acepta un `id` con la forma `EMP-` seguida de 4 dígitos, o un nombre de hasta 80 caracteres.
   - `search_by_department` solo acepta un departamento que exista en el directorio.
   - Un argumento inválido no llama al directorio: la herramienta devuelve un error que el agente puede leer y se
     registra en la auditoría.
5. **Detección de inyección de instrucciones.**
   - Una lista corta de frases, comparadas sin acentos ni mayúsculas con `fold_text`. Por ejemplo: «ignora las
     instrucciones», «ignore previous instructions», «olvida tus reglas», «muestra tu prompt», «system prompt»,
     «actúa como».
   - Solo **se detecta y se audita**. La petición sigue su curso, porque el agente ya está acotado a dos herramientas
     de solo lectura.
6. **Auditoría de seguridad.**
   - Cada detección escribe un evento `security` en el log JSON con estos campos: `request_id`, `client`, `stage`
     (`input` u `output`), `control` (`pii`, `secret`, `output_invalid`, `tool_args` o `injection`) y `kinds` (la
     lista de tipos).
   - **Nunca escribe el valor detectado.**
   - Los mismos datos van a los metadatos de la traza de LangSmith.
7. **Métricas.** `GET /metrics` agrega `security`, un conteo por control, por ejemplo
   `{"pii": 3, "injection": 1, ...}`. Las llaves que ya existen no cambian.
8. **Respuesta de `/ask`.** Agrega el campo `redactions`: la lista de tipos ocultados en la pregunta o en la
   respuesta, sin repetir. Una lista vacía significa que no se ocultó nada. Los campos que ya existen no cambian.
9. **Concurrencia.** Una prueba manda **20 peticiones `/ask` al mismo tiempo** (con hilos y el modelo simulado) y
   comprueba cuatro cosas:
   - Todas responden `200`.
   - Cada una tiene un `request_id` distinto.
   - `/metrics` cuenta exactamente 20 peticiones a `/ask`.
   - El límite de peticiones sigue contando bien por cliente.
10. **Documentación.**
    - `product/doc/security.md`: una tabla con **todos los controles de seguridad** del producto, los de la sesión 4
      y los nuevos. Tiene tres columnas: el control, dónde está en el código y cómo se comprueba.
    - Una sección de trade-offs: por qué expresiones regulares y no un modelo de PII, qué falsos positivos y
      negativos son posibles, y por qué la inyección se audita y no se bloquea.
    - Un ADR nuevo en `product/doc/adr/` para la detección de PII y la validación de salidas.
    - Actualizar `product/doc/compliance-checklist.md` y `product/README.md`.

## Configuración nueva

| Variable | Por omisión | Para qué |
| --- | --- | --- |
| `MAX_ANSWER_CHARS` | `2000` | Largo máximo de la respuesta |

## Cómo se comprueba

- Pruebas unitarias de `app/pii.py`. Cada tipo de PII tiene un caso positivo y un caso negativo. Por ejemplo, un
  número de 16 dígitos que **no** pasa Luhn no se oculta, y `EMP-0001` y «Ana López» no se ocultan nunca.
- Escenarios Gherkin:
  - Una pregunta con un correo responde `200` y `redactions` contiene `email`.
  - El log y la traza no contienen el correo.
  - El modelo simulado recibe el texto limpio.
- Prueba de que una clave de `API_KEYS` que aparece en la respuesta del modelo simulado sale como
  `[REDACTED:secret]`.
- La prueba de concurrencia del punto 9.
- `verification unit`, `contract`, `qa`, `e2e` y `evaluate` siguen pasando, con cobertura de 80 % o más.
- Después de publicar: `uv run python -m verification production <url>`.
