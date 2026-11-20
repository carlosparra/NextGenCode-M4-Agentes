# 0007. Palancas de costo medibles: enrutador por regla, ventana y precio por nombre de modelo

## Contexto

Cada respuesta debe costar menos sin empeorar. Las palancas tienen que medirse sin red ni cuota, con el modelo
simulado, y la evaluación compara línea base (`ROUTING=false`, `HISTORY_WINDOW=1000`) contra la configuración
por omisión.

## Decisión

- `router.py` elige el modelo con una regla pura en código: `MODEL_LARGE` si el enrutamiento está apagado, la
  pregunta pasa de `ROUTER_MAX_CHARS` o contiene una palabra clave (sin distinguir mayúsculas ni acentos); si no,
  `MODEL_SMALL`. Devuelve también el motivo (`route`).
- Hay un modelo por nombre (`MODEL_SMALL`, `MODEL_LARGE`), tanto simulado como real; el agente recibe el elegido.
- La ventana `HISTORY_WINDOW` recorta solo el historial del cliente, nunca los mensajes del bucle en curso.
- `pricing.py` calcula el costo por llamada con `data/model_prices.json`; una llamada cacheada cuesta 0. Un
  modelo configurado sin precio impide arrancar.

## Consecuencias

- El enrutamiento es explicable y gratis, pero no entiende el significado: preguntas complejas sin palabra
  clave van al modelo pequeño.
- Con el simulado la calidad es igual en ambos modelos; el ahorro se ve en precio y en tokens de entrada.
- Cambiar precios es editar el JSON, sin tocar código.
