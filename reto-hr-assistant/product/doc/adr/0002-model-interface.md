# 0002. Interfaz de modelo `complete(messages)` y modelo simulado

Estado: reemplazado en parte por los ADR 0007 y 0008

Sigue vigente: el protocolo `LanguageModel` con `complete(messages) -> ModelReply`, el protocolo de texto con un
único objeto JSON, `FakeModel` con sus cuatro reglas y la inyección del modelo en `create_app()`.
Queda reemplazado: la construcción con `build_model` y un solo proveedor (ADR 0007 y 0008) y la promesa de que
`agent.py` no cambia (ADR 0007 y 0008). Las partes reemplazadas se marcan abajo con [reemplazado].

## Contexto

El agente necesita un modelo de lenguaje, pero en esta sesión no hay red ni presupuesto, y más adelante se
querrá cambiar de proveedor sin reescribir el agente. Las pruebas deben ser deterministas.

## Decisión

El agente depende solo del protocolo `LanguageModel` con `complete(messages) -> ModelReply`
(`text`, `input_tokens`, `output_tokens`). El texto es siempre un único objeto JSON: `{"tool", "args"}` o
`{"answer"}`. `FakeModel` implementa las cuatro reglas de la especificación y cuenta tokens por palabras.
`create_app()` recibe el modelo como dependencia para que las pruebas inyecten modelos guionados.

[reemplazado] `build_model(settings, directory)` elige la implementación según `MODEL_PROVIDER`; hoy solo `fake`.
Ahora: `build_models(settings, directory, http_client=None)` devuelve un diccionario `{nombre: LanguageModel}`
con `MODEL_SMALL` y `MODEL_LARGE`, y acepta los proveedores `fake` y `gateway` (`GatewayModel`, ADR 0007;
modelos por nombre, ADR 0008). `build_model` se conserva solo por compatibilidad y con `gateway` devuelve
`MODEL_LARGE`. `ModelReply` agrega `cached` (por omisión `False`, ADR 0007).

## Consecuencias

- [reemplazado] Agregar un proveedor real es una clase nueva y una rama en `build_model`; `agent.py` no cambia.
  Ahora: un proveedor nuevo es una clase nueva y una rama en `build_models`, pero `agent.py` sí cambió al llegar
  el gateway y el enrutador: `Agent` recibe un modelo o un diccionario de modelos por nombre,
  `run(..., model_name=...)` usa el modelo elegido en todas las vueltas, `AgentResult` cuenta `cached_calls` y
  tokens cobrables, y `extract_json_object` extrae el primer objeto JSON del texto (ADR 0007 y 0008).
- El agente debe tolerar respuestas fuera del protocolo, aunque el modelo simulado nunca las produzca.
- El conteo de tokens de `FakeModel` es aproximado y no sirve para facturación; el de `GatewayModel` viene de
  `usage` del proveedor (ADR 0007).
