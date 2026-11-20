# 0004. Configuración validada al arrancar e inyección de dependencias

## Contexto

La configuración llega por variables de entorno. Un valor inválido (por ejemplo `AGENT_MAX_STEPS=0`)
descubierto en mitad de una petición daría errores confusos. Además, las pruebas necesitan cambiar
configuración, modelo y directorio sin tocar el entorno real ni leer `.env`.

## Decisión

`config.load_config(environ)` recibe un diccionario, aplica valores por omisión y valida todo de una vez;
ante un valor inválido lanza `ConfigError` con un mensaje en español que nombra la variable. `main.py`
construye `app` de módulo con `load_config(os.environ)`, `load_directory` y `build_model`, de modo que el
proceso no arranca si algo falla. `create_app(config, model, directory)` recibe las tres dependencias ya
construidas y no lee el entorno.

## Consecuencias

- Los errores de configuración aparecen al arrancar, no ante el primer usuario.
- Las pruebas inyectan `environ`, modelos de prueba y directorios sin variables globales.
- Agregar una variable es un campo y una validación en `config.py`; `MODEL_PROVIDER` distinto de `fake`
  se rechaza en esta sesión.

## Nota de actualización (sesión 4)

La decisión de fondo sigue vigente: todo se valida al arrancar y `create_app` recibe sus dependencias ya
construidas, sin leer el entorno. Cambiaron los nombres y las firmas, y una consecuencia quedó reemplazada:

- `main._build_default_app()` arma la app con `load_config(os.environ)`, `load_directory(...)`,
  `pricing.load_prices(...)` y `llm.build_models(config, directory, http_client=None)`, que devuelve un modelo
  por nombre (`MODEL_SMALL` y `MODEL_LARGE`). `build_model` ya no existe.
- La firma actual es `create_app(config, models, directory, prices, observability=None, *, rate_limiter=None)`.
  También falla al arrancar (`ConfigError`) si un modelo configurado no tiene precio (ADR 0007).
- La frase "`MODEL_PROVIDER` distinto de `fake` se rechaza en esta sesión" quedó reemplazada por el ADR 0006:
  hoy se admiten `fake` y `gateway`, y con `gateway` `load_config` exige las variables `CF_*`.
- Con `ENVIRONMENT=production`, `load_config` además aplica `compliance.check_production(config)` y lanza un
  solo `ConfigError` con todas las reglas incumplidas (ADR 0011). Es el mismo principio de fallar al arrancar.
