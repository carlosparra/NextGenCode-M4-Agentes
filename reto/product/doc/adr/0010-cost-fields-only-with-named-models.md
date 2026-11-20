# 0010. Los campos de costo de /ask solo se reportan con modelos con nombre

Estado: propuesto

## Contexto

La sesión 3 agrega a `POST /ask` los campos `model`, `route`, `cached_calls` y `cost_usd`. Una prueba de la
sesión 1 exige que `/ask` devuelva exactamente seis campos cuando se inyecta un modelo con `create_app(llm=...)`.
Ese modelo inyectado no tiene nombre conocido, así que no hay precio con el que calcular un costo honesto.

## Decisión

- Con `create_app(llm=...)` el mismo modelo atiende los dos nombres, `/ask` omite los cuatro campos de costo
  (`response_model_exclude_none`) y no suma a `/metrics.cost_usd`.
- Sin `llm` (incluida `app = create_app()`), los modelos se construyen con `build_models` y los cuatro campos
  siempre están en la respuesta.

## Consecuencias

- Las pruebas de las sesiones 1 y 2 no cambian, y el contrato 03 pasa con la app real.
- `/ask` tiene dos formas; se limita a pruebas y se fija con una prueba unitaria.
- Si en el futuro se retira la prueba de seis campos, esta excepción puede eliminarse.
