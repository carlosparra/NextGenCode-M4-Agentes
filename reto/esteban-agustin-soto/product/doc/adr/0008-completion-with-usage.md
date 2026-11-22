# 0008. Los modelos devuelven uso real y estado de caché

## Contexto
Para costear una respuesta hace falta saber los tokens reales y si el gateway respondió `HIT`. Con `complete(messages)` que devuelve solo texto, el agente solo puede contar palabras. Un estado guardado en el modelo (por ejemplo `last_usage`) fallaría con peticiones concurrentes.

## Decisión
Los modelos agregan `generate(messages)`, que devuelve un `Completion` inmutable con `text`, `input_tokens`, `output_tokens` y `cached`. `complete` se conserva y devuelve el texto. El agente usa `generate` si existe y, si no, `complete` con conteo aproximado. `FakeModel` y `GatewayModel` implementan ambos. Toda falla del gateway se convierte en `ModelUnavailable`, que la API responde como `502`.

## Consecuencias
- Cada llamada trae sus propios datos, sin estado compartido; el servicio sigue sin estado.
- Las pruebas y dobles de las sesiones 1 y 2 siguen funcionando.
- Hay dos métodos en la interfaz mientras `complete` no se retire.
