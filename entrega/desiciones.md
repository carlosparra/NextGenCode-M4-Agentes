# Decisiones: el modelo de Cloudflare no respondía bien

Este documento recoge el problema inicial del HR Assistant, cómo se diagnosticó, qué se decidió en cada punto y con
qué evidencia. Los prompts están copiados tal como se escribieron, con sus erratas. Las pruebas y los logs son los
que se proporcionaron durante el trabajo o los que se obtuvieron al ejecutar las verificaciones.

## 1. Resumen

| | |
| --- | --- |
| **Síntoma** | Con `MODEL_PROVIDER=gateway`, cada consulta terminaba en «No pude completar la respuesta. Intenta con una pregunta más concreta.» o el modelo decía que le faltaba contexto |
| **Causa 1** | `GatewayModel` mandaba solo la conversación al modelo: ni mensaje `system` ni herramientas. El modelo no sabía que existían `get_employee` y `search_by_department` |
| **Causa 2** | Con el `system` ya presente, el modelo pequeño (`llama-3.1-8b-instruct-fast`) mezclaba formatos y el agente no se recuperaba: el parser exigía JSON puro y el reintento repetía la misma petición |
| **Solución** | Mensaje `system` en `GatewayModel`, lectura tolerante de la salida, mensaje de corrección en el reintento |
| **Resultado** | Probado a mano con el modelo pequeño: funcionó. Después, la fábrica reprodujo el arreglo desde la especificación (ver `sesion05.md`) |
| **Por qué no se vio antes** | Todas las verificaciones de la fábrica corrían con el modelo simulado, que decide con reglas y no necesita instrucciones |

## 2. Cronología, prompts y decisiones

### 2.1. Teorías iniciales

**Prompt**

> claude, dentro de sesion04/product hay una aplicación que consulta un modelo de ia para consultar empleados que estan en sesion04/product/data/employees.json, pero cada que hago la consulta el modelo de ia me responde que no puede procesar porque le falta contexto, en teoria el llamado al modelo de ia debería llevar un conjunto de herramientas para que la ia resuelva con cual puede obtener el empleado, teoriza sobre que podría estar pasando

**Qué se encontró.** En `app/llm.py`, `GatewayModel.complete` armaba el cuerpo así:

```python
body = {
    "model": model,
    "messages": messages,
    "max_tokens": self._config.model_max_tokens,
    "temperature": self._config.model_temperature,
}
```

No había campo `tools` ni mensaje `system`. El agente (`app/agent.py`) esperaba que el modelo contestara
`{"tool": ..., "args": ...}` o `{"answer": ...}`, pero nada se lo decía al modelo. `FakeModel` funcionaba porque decide
con expresiones regulares sobre el último mensaje.

**Decisión.** Tratar la falta de instrucciones como causa principal y listar teorías secundarias: respuesta que no es
JSON (el bucle reintenta sin corregir), caché del gateway, preguntas sin id ni departamento, modelos sin soporte de
function calling e historial recortado.

### 2.2. Cómo informar las herramientas

**Prompt**

> sin implementar cambios en codigo, como sería el ajuste para informarle las herramientas al modelo?

| Opción | Cómo | Ventaja | Costo |
| --- | --- | --- | --- |
| **A. Prompt de sistema con protocolo JSON** | Un mensaje `system` que describe herramientas y formato | Funciona con cualquier modelo que siga instrucciones; no toca la interfaz `Model` | Depende de que el modelo obedezca |
| B. Function calling nativo | Campo `tools` en el body | El modelo y el servidor ayudan a validar | La respuesta llega en `tool_calls`, hay que cambiar `Completion` y el protocolo, y no todos los modelos de Workers AI lo soportan |

**Decisión: opción A.** El agente ya parsea JSON como texto; el enrutador alterna entre un modelo de 8B y uno de 70B;
y la opción B cambiaría el contrato de la interfaz del modelo (ADR 0002).

### 2.3. Aplicar el arreglo en el código

**Prompt**

> implementa los cambios en codigo, después haremos el ajuste en la fabrica para corregir desde la fuente el problema

**Decisión: dónde poner el prompt.** Se propuso inicialmente en `Agent._run`, pero varias pruebas asumen que el primer
mensaje es el historial y cuentan los mensajes enviados (`history_window`, «the model received N messages»). Un
`system` dentro del agente las habría roto. Se puso en `GatewayModel`, que es donde estaba el fallo, y así `FakeModel`
y el agente no cambian.

**Decisión: departamentos reales.** `GatewayModel` recibe `directory` (opcional) y el prompt lista los departamentos
existentes, para que el modelo use nombres exactos.

**Primera versión del prompt** (la que se vio en el log de Cloudflare, sección 2.5):

```text
Eres el asistente de RR. HH. Solo puedes consultar el directorio de empleados con estas herramientas:
1. get_employee(employee_id): devuelve un empleado por su id (formato EMP-0001).
2. search_by_department(department): lista los empleados de un departamento. Departamentos existentes: Tecnología, Ventas, Finanzas.

Responde SIEMPRE con un único objeto JSON, sin texto adicional ni markdown. Hay tres formas válidas:
{"tool": "get_employee", "args": {"employee_id": "EMP-0001"}}
{"tool": "search_by_department", "args": {"department": "Ventas"}}
{"answer": "texto de la respuesta para la persona"}

Después de pedir una herramienta recibirás un mensaje "Resultado de la herramienta: ...". Con ese resultado responde con {"answer": ...}. Si falta el id o el departamento, pídelo con una respuesta. No inventes datos que no estén en el resultado de una herramienta.
```

Resultado de las pruebas en ese punto: 104 pasaron (las BDD no corrieron porque `pytest_bdd` no estaba instalado en el
entorno global).

### 2.4. Dónde debía corregirse en la fábrica

**Prompt**

> realiza un análisis para ver en que parte de la fabrica podría ir esa especificacion

**Hallazgo.** La especificación `01-architecture.md` definía el protocolo de salida pero no decía que el modelo debía
recibir instrucciones. `03-costs.md` fijaba el cuerpo del request como `{"model", "messages", "max_tokens",
"temperature"}` sin mencionar un `system`. Además, ninguna verificación usaba un modelo real. Esto se desarrolla en
`sesion05.md`.

### 2.5. Aclaración sobre los modelos

**Prompt**

> aclarame algunas dudas antes de proceder, los modelos como el que estamos usando de cloudflare, necesitan que les informemos de las herramientas disponibles en el agente?

**Respuesta resumida.** Sí. Un modelo no tiene acceso al código del agente: solo ve el cuerpo de la petición. Hay dos
canales (prompt de sistema o `tools`), pero en ambos hay que informar. Workers AI documenta function calling solo para
algunos modelos; no se confirmó que el 8B lo soporte, por eso se mantuvo el prompt.

### 2.6. El `system` llega, pero el modelo pequeño sigue fallando

Después de aplicar el prompt, la persona observó que el resultado seguía siendo el mensaje de tope.

**Prompt**

> en los logs veo que ya se envia el promp system, sin embargo, como resultado final en vez de traerme al usuario sigue respondiendo
>
> No pude completar la respuesta. Intenta con una pregunta más concreta.
> ID de petición: 52d62c7a-abf0-479d-90bd-d8230658f484
> Herramientas usadas: ninguna
>
> este es el request que veo registrado en cloudflare

**Log de Cloudflare: request** (proporcionado)

```json
{
  "model": "@cf/meta/llama-3.1-8b-instruct-fast",
  "messages": [
    {
      "role": "system",
      "content": "Eres el asistente de RR. HH. Solo puedes consultar el directorio de empleados con estas herramientas:\n1. get_employee(employee_id): devuelve un empleado por su id (formato EMP-0001).\n2. search_by_department(department): lista los empleados de un departamento. Departamentos existentes: Tecnología, Ventas, Finanzas.\n\nResponde SIEMPRE con un único objeto JSON, sin texto adicional ni markdown. Hay tres formas válidas:\n{\"tool\": \"get_employee\", \"args\": {\"employee_id\": \"EMP-0001\"}}\n{\"tool\": \"search_by_department\", \"args\": {\"department\": \"Ventas\"}}\n{\"answer\": \"texto de la respuesta para la persona\"}\n\nDespués de pedir una herramienta recibirás un mensaje \"Resultado de la herramienta: ...\". Con ese resultado responde con {\"answer\": ...}. Si falta el id o el departamento, pídelo con una respuesta. No inventes datos que no estén en el resultado de una herramienta."
    },
    {
      "role": "user",
      "content": "empleado EMP-0003"
    }
  ],
  "max_tokens": 300,
  "temperature": 0
}
```

**Log de Cloudflare: respuesta** (proporcionada)

```json
{
  "id": "id-1795151166754",
  "object": "chat.completion",
  "created": 1795151166,
  "model": "@cf/meta/llama-3.1-8b-instruct-fast",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Resultado de la herramienta: {\"tool\": \"get_employee\", \"args\": {\"employee_id\": \"EMP-0003\"}} \n\n{\"answer\": \"Empleado no encontrado\"}",
        "refusal": null,
        "annotations": null,
        "audio": null,
        "function_call": null,
        "reasoning": null
      },
      "logprobs": null,
      "finish_reason": "stop",
      "stop_reason": null,
      "token_ids": null,
      "routed_experts": null
    }
  ],
  "usage": {
    "prompt_tokens": 256,
    "completion_tokens": 36,
    "total_tokens": 292,
    "prompt_tokens_details": {
      "cached_tokens": 0
    },
    "neurons": 2.309593677520752
  }
}
```

**Diagnóstico.** El modelo devolvió un solo texto con tres cosas mezcladas: (1) el prefijo
`Resultado de la herramienta:`, que solo debería escribir el agente; (2) la petición correcta de `get_employee` con
`EMP-0003`; y (3) una respuesta inventada («Empleado no encontrado») sin esperar el resultado.

Por qué terminaba en el mensaje de tope:

1. `_parse` hacía `json.loads` del texto completo. Ese texto no era JSON válido y devolvía `None`.
2. El bucle hacía `continue` sin cambiar `messages`, así que el siguiente paso mandaba exactamente la misma petición.
3. Con `temperature: 0` el modelo respondía lo mismo (y con caché activa ni siquiera había llamada nueva).
4. Se agotaban los pasos y salía `CAP_MESSAGE`. `Herramientas usadas: ninguna` cuadra: la herramienta nunca corría.

**Teorías sobre el modelo.** (1) El prompt citaba literalmente `Resultado de la herramienta: ...` y un modelo de 8B
tiende a repetir lo que ve; (2) nada le decía que diera una sola acción por respuesta; (3) el enrutador mandaba la
pregunta al modelo pequeño; (4) no había un ejemplo; (5) no se forzaba el formato con `response_format`.

### 2.7. Contraste con el modelo grande

**Prompt**

> al forzar el modelo grande me respondió esto
>
> El empleado EMP-0004 es Jorge Díaz, quien se desempeña como Líder técnico en el departamento de Tecnología y está activo desde el 10 de enero de 2022.
> ID de petición: 0434f445-6ede-4a3e-82fc-9c5f9a9c6db3
> Herramientas usadas: get_employee

**Conclusión.** El prompt funciona y el ciclo del agente funciona de punta a punta con `llama-3.3-70b`. El fallo era del
modelo pequeño, que es justo el que el enrutador usa para las preguntas simples, las más comunes del producto. Esto
confirmó la teoría de que el 8B necesita un agente que tolere y corrija su formato.

### 2.8. Segundo arreglo en el código

**Prompt**

> aplica los cambios al código dentro de product/ en la carpeta de sesion05 para confirmar y corregir el problema en codigo, después haremos los cambios pertinentes en la fabrica

**Decisiones** (cinco cambios, del más importante al más ligero):

| # | Cambio | Archivo | Por qué |
| --- | --- | --- | --- |
| 1 | Parser tolerante: si el texto completo no es JSON, usar el primer objeto JSON válido con `tool` o `answer` | `agent.py` | La salida real del 8B habría ejecutado `get_employee` con `EMP-0003`; lo inventado se ignora |
| 2 | Mensaje de corrección en el reintento, tanto para salida ilegible como para herramienta rechazada | `agent.py` | Con `temperature: 0` repetir la petición es repetir el fallo |
| 3 | Quitar del prompt la cita literal del prefijo del resultado | `llm.py` | Probable causa de que el 8B lo repitiera |
| 4 | Regla de una sola acción por respuesta y de no imaginar el resultado | `llm.py` | Evita simular el ciclo completo en un mensaje |
| 5 | Ejemplo completo de una consulta | `llm.py` | Ayuda a los modelos pequeños |

**Prueba que reproduce el log real** (se agregó en `tests/test_agent_edge_cases.py`):

```python
SMALL_MODEL_MIXED_REPLY = (
    "Resultado de la herramienta: "
    '{"tool": "get_employee", "args": {"employee_id": "EMP-0004"}} \n\n'
    '{"answer": "Empleado no encontrado"}'
)


def test_text_around_the_json_does_not_hide_the_tool_request(directory):
    model = ScriptedModel([SMALL_MODEL_MIXED_REPLY, answer_reply("Jorge")])
    result = Agent(model, directory, max_steps=3).run("empleado EMP-0004")
    assert result["tools_used"] == ["get_employee"]
    assert "Jorge Díaz" in model.calls[1][-1]["content"]
    assert result["answer"] == "Jorge"
```

Pruebas relacionadas del mismo cambio: bloque markdown con JSON, texto sin objeto del protocolo, salida inválida
corregida en vez de repetida, herramienta rechazada explicada al modelo, y el prompt sin el prefijo.
Resultado: 109 pruebas pasaron sin las BDD y 155 con ellas (usando el entorno de `sesion04`).

**Qué no se pudo cubrir con simulaciones.** Cómo reaccionaría el 8B real al prompt nuevo. La persona lo comprobó:

**Prompt**

> ya se pudieron ejecutar las pruebas para el modelo pequeño y funcionó bien, ahora vamos a corregir desde las especificaciones de la fábrica en la carpeta sesion05, haz un plan y especifica que cambios se harán, no modifiques archivos todavia

El arreglo manual quedó confirmado con el modelo pequeño real. Ese código se descartó después a propósito para que la
fábrica lo reconstruyera desde la especificación (ver `sesion05.md`).

### 2.9. Confirmación en producción

Con el producto reconstruido por la fábrica y publicado en https://hr-manager-lks0.onrender.com/, la persona compartió
este pantallazo:

![HR Assistant en producción](evidencia-produccion.png)

La consulta «quien es el empleado EMP-0003?» es la misma que fallaba en el log de la sección 2.6 («empleado EMP-0003»):
antes terminaba en el mensaje de tope; ahora devuelve «EMP-0003 es Marta Ruiz, Desarrolladora de Tecnología...» con
`get_employee`. La segunda consulta, «Tecnología», lista a los tres empleados de ese departamento con
`search_by_department`. Por la regla del enrutador, ambas preguntas van al modelo pequeño, el que fallaba al principio.

Dos detalles que la captura deja ver y que quedan como pendientes de calidad, no del arreglo: la segunda consulta
ejecutó la herramienta dos veces, y la primera respuesta dice «baja desde 2016-11-02», cuando esa fecha es la de ingreso
y «baja» es el estado. Probablemente se debe a cómo el agente formatea el resultado («..., desde 2016-11-02, baja»).
Detalle en `reporte.md`, sección 1.4.

## 3. Resumen de decisiones

| # | Decisión | Alternativa descartada | Motivo |
| --- | --- | --- | --- |
| D1 | Informar las herramientas con un mensaje `system` | Function calling nativo (`tools`) | Funciona con cualquier modelo; no cambia el contrato de la interfaz ni `Completion` |
| D2 | El `system` lo agrega `GatewayModel` | Agregarlo en `Agent` | No rompe las pruebas que cuentan mensajes ni el modelo simulado |
| D3 | Listar los departamentos reales en el prompt | Texto fijo | El modelo usa nombres exactos |
| D4 | No citar el prefijo del resultado en el prompt | Citarlo para explicar el formato | El 8B lo repitió como si fuera suyo |
| D5 | Una sola acción por respuesta, con ejemplo completo | Solo describir el formato | Evita que el modelo simule el ciclo completo |
| D6 | Parser tolerante en el agente | Esperar que el modelo cumpla siempre | Un modelo pequeño volverá a salirse del formato; el agente debe tolerarlo |
| D7 | Mensaje de corrección en el reintento | Repetir la misma petición | Con `temperature: 0` se repite el mismo fallo |
| D8 | Corregir primero en código para confirmar y después en la fábrica | Ir directo a la fábrica | Separa «el arreglo funciona» de «la fábrica lo produce» |
| D9 | No usar `response_format` ni `tools` nativos | Probarlos | No se confirmó el soporte en el 8B; el arreglo ya funcionaba sin ellos |

## 4. Observaciones y riesgos abiertos

- **Caché del gateway.** Con `CACHE_TTL_SECONDS` mayor que 0, una respuesta mala antigua puede seguir saliendo hasta
  expirar, aunque cambie el prompt.
- **El mensaje `system` suma tokens de entrada** (256 `prompt_tokens` en el log de arriba para una pregunta corta). Al
  ser un prefijo estable, favorece la caché del gateway. Con el prompt final de la fábrica, que incluye un ejemplo, una
  consulta de dos llamadas gastó 782 tokens de entrada en producción (`reporte.md`, secciones 2.2 y 3.3).
- **Pregunta por nombre.** Ninguna herramienta busca por nombre, solo por id o departamento. Una pregunta como
  «¿quién es Ana?» no tiene herramienta que la resuelva, aunque el modelo conozca las otras dos.
- **La prueba de humo de producción** solo comprueba que `/ask` responda 200; no habría detectado este fallo. Por eso
  el skill `iterate` pide una comprobación manual con «¿Quién es EMP-0004?» en la página desplegada.
- **Ejemplo del prompt de la fábrica.** El ejemplo completo que generó la fábrica usa datos que no están en el
  directorio real (`Ana Pérez, Ingeniera, Ingeniería`, frente a `Ana López, Analista de datos, Tecnología`). Es
  inofensivo mientras el modelo no los copie, pero conviene usar un ejemplo que no se pueda confundir con datos reales.
- **Un modelo siempre puede salirse del formato.** La corrección y el tope acotan el daño; no lo eliminan.
