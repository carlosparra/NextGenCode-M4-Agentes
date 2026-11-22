# 0001. API sin estado

## Contexto
El personal de RH usa el asistente desde una página web y se quiere escalar sin coordinar copias.

## Decisión
La API no guarda nada entre peticiones. El cliente manda el historial en `history` y el agente se crea por petición con dependencias inyectadas en `create_app()`.

## Consecuencias
- Escalar es correr más copias detrás de un balanceador.
- Cada petición es más grande, porque lleva el historial.
- El servidor no puede recuperar conversaciones si el navegador las pierde.
