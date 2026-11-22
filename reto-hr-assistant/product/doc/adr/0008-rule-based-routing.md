# 0008. Enrutamiento por regla en código y modelos por nombre

Estado: propuesto

## Contexto

Mandar todo al modelo grande es caro; la mayoría de las preguntas (un empleado, un departamento) las resuelve el
pequeño. Usar otro modelo para decidir costaría tokens y sería poco repetible. Las palancas se deben poder medir
sin red con el modelo simulado.

## Decisión

`routing.choose_model(question, settings)` devuelve `Route(model, reason)`: `MODEL_LARGE` si `ROUTING=false`
(`routing_disabled`), si la pregunta pasa de `ROUTER_MAX_CHARS` (`long_question`) o si contiene «compara»,
«resume», «explica», «por qué», «analiza» o «todos» (`keyword:<palabra>`, sin distinguir mayúsculas ni acentos);
si no, `MODEL_SMALL` (`default_small`). Desde el reto, las palabras clave se comparan como **palabras completas**
sobre el texto normalizado, no por subcadena: «resumen» no activa «resume», y las preguntas de `department_summary`
van al modelo chico porque el cálculo lo hace el código (ADR 0014). El modelo se elige una vez por pregunta y se usa
en todas las vueltas. `build_models` devuelve un diccionario `{nombre: LanguageModel}`; con `fake` son dos
`FakeModel` que responden igual. El agente recibe ese diccionario y el nombre elegido; el costo se calcula con ese
nombre.

## Consecuencias

- La regla es determinista, gratis y se prueba con pruebas unitarias simples; `test_routing.py` fija que «resumen»
  va al chico.
- Formas derivadas («explícame», «analizar», «comparación») ya no coinciden y van al chico; si la evaluación muestra
  que baja la calidad, se agregan a la lista.
- `model` y `route` viajan en la respuesta y en `agent_run`, para explicar cada costo.
- Si se inyecta un solo modelo en `create_app`, sirve para ambos nombres: las pruebas anteriores siguen igual.
