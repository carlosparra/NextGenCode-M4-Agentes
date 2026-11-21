# Sesión 5 · El modelo real entiende al agente

Parte del producto de las sesiones 1 a 4. Con el modelo simulado todo funcionaba, pero un modelo real no conoce el
código del agente: solo sabe lo que viaja en cada petición, y un modelo pequeño tiende a salirse del formato. Hoy,
con `MODEL_PROVIDER=gateway`, el modelo no recibe las herramientas y, cuando mezcla texto con JSON, el agente
repite la misma petición hasta agotar el tope y contesta «No pude completar la respuesta».

Esta sesión no agrega funciones: hace que el agente funcione con un modelo real, también con el pequeño.

## Lo que debe hacer

1. **El modelo real recibe las instrucciones.** Cada llamada a `GatewayModel` lleva como **primer mensaje** uno con
   `role: "system"`, antes del historial y la pregunta. Debe decir:
   - Las herramientas, con nombre y argumentos: `get_employee(employee_id)` y `search_by_department(department)`.
   - Los nombres exactos de los departamentos que existen en los datos, tomados del directorio.
   - Que cada respuesta es **un solo objeto JSON**, sin texto extra ni markdown, con una de tres formas: pedir
     `get_employee`, pedir `search_by_department` o `{"answer": "..."}`.
   - Que cada respuesta es **una sola acción**: o pide una herramienta o responde, nunca las dos. Tras pedir una
     herramienta, el modelo se detiene: el sistema la ejecuta y le manda el resultado en el siguiente mensaje.
   - Que no inventa datos que no vengan de una herramienta, y que si falta el id o el departamento, lo pide con una
     respuesta.
   - Un ejemplo completo de una consulta (pregunta, petición de herramienta, resultado, respuesta).

   El texto **no cita** el prefijo `Resultado de la herramienta: `: un modelo pequeño lo repite como si fuera suyo.
   Lo agrega la clase `GatewayModel`, no el agente, y el modelo simulado no lo necesita. Así `HISTORY_WINDOW`, el
   historial y el tope del bucle no cambian.
2. **Lectura tolerante de la salida.** Si el texto completo del modelo no es JSON, el agente usa el **primer objeto
   JSON válido** que contenga `tool` o `answer`. Así se entiende una respuesta con texto antes o después, con un
   bloque de markdown o con dos objetos (se usa el primero y se ignora el resto). Un texto sin ningún objeto del
   protocolo sigue siendo un paso fallido.
3. **Corrección de la salida inválida.** Si la salida no se puede interpretar, o la herramienta pedida o sus
   argumentos no son válidos, el agente agrega un mensaje `user` que lo explica y le recuerda el formato. La
   siguiente petición al modelo **no es idéntica** a la anterior. Sigue contando como un paso del tope: el mensaje
   «No pude completar la respuesta. Intenta con una pregunta más concreta.» no cambia.
4. **Lo que no cambia.** La URL del gateway (`https://gateway.ai.cloudflare.com/v1/{CF_ACCOUNT_ID}/{CF_GATEWAY_ID}/workers-ai/v1/chat/completions`),
   el cuerpo con `model`, `messages`, `max_tokens` y `temperature`, el contrato `GatewayModel(config, transport=None)`,
   las llamadas con `httpx` y la API de `POST /ask`. No hay variables de configuración nuevas.

## Pruebas unitarias (las escribe `qa-unit`)

Con el transporte de `httpx` inyectado (`httpx.MockTransport`); nunca se llama a la red:

- La petición al gateway lleva `system` primero, nombra las dos herramientas y los departamentos, y no contiene el
  prefijo `Resultado de la herramienta: `.
- Una respuesta con texto alrededor del JSON, la que mezcla una petición de herramienta con una respuesta inventada,
  ejecuta la herramienta y descarta lo demás.
- Un bloque de markdown con JSON se entiende.
- Texto sin objeto del protocolo es un paso fallido; un objeto sin `tool` ni `answer` también.
- Tras una salida inválida o una herramienta rechazada, la siguiente petición lleva un mensaje más y no es igual a la
  anterior.

Estas pruebas no cuentan para el tope de pruebas nuevas por sesión de `qa-unit`.

## Cómo se comprueba

- `uv run python -m verification unit`: las pruebas del producto pasan con cobertura de 80 % o más.
- `uv run python -m verification contract`: ahora incluye `verification/contract/test_contract_model.py`. La
  verificación arranca el producto con `MODEL_PROVIDER=gateway` y **simula a Cloudflare dentro del proceso del
  producto**, sustituyendo el transporte de `httpx` para las llamadas a `gateway.ai.cloudflare.com`. El producto no
  se modifica, pero **debe usar `httpx` y la URL exacta** de arriba. Comprueba, desde afuera, que:
  - la primera petición lleva el mensaje `system` con las herramientas y los departamentos;
  - una salida desordenada, como la de un modelo pequeño, termina con el empleado correcto y `get_employee` usada;
  - una salida inválida se corrige y no se repite la misma petición;
  - un modelo que nunca responde bien termina con el mensaje del tope.
- `qa`, `e2e` y `evaluate`, como en la sesión 4.
