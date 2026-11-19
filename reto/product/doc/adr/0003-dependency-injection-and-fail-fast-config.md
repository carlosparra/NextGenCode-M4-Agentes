# 0003. Inyección de dependencias en create_app y configuración que falla rápido

Estado: propuesto

## Contexto

QA.md exige inyección de dependencias y comportamiento determinista. La especificación pide que un valor de
configuración inválido impida arrancar con un mensaje claro, y que las pruebas puedan cambiar el modelo y los
datos.

## Decisión

- `create_app(settings=None, llm=None, directory=None, *, clock=None, log_stream=None, metrics=None, tracer=None,
  http_client=None)` recibe sus dependencias; si faltan, las construye desde el entorno. Los argumentos con
  palabra clave se agregaron en las sesiones 2 y 3 sin romper las llamadas previas. `main.py` expone además
  `app = create_app()` para uvicorn.
- `load_settings(env)` recibe un mapeo (no lee `os.environ` por dentro) y devuelve un `Settings` inmutable.
  Valida tipos y rangos de todas las variables y lanza `ConfigError` con el nombre de la variable; los secretos
  (`LANGSMITH_API_KEY`, `CF_API_TOKEN`) nunca aparecen en el mensaje.
- Las rutas relativas (`EMPLOYEES_PATH`, `PRICES_PATH`) se resuelven contra la carpeta `product/`.

## Consecuencias

- Las pruebas construyen la app con dobles (incluido un `httpx.Client` con transporte falso), sin red ni archivos
  reales.
- Un despliegue mal configurado falla al iniciar, no en la primera petición.
- Importar `app.main` con un entorno inválido lanza error; las pruebas deben usar `create_app(...)`.
- Inyectar `llm=` cambia la forma de `/ask` (ADR 0010).
