# 0001. API sin estado con historial enviado por el cliente

Estado: propuesto

## Contexto

El HR Assistant debe escalar corriendo más copias de la API, y una conversación necesita contexto de turnos
anteriores. Guardar sesiones en el servidor obligaría a compartir almacenamiento o fijar clientes a una copia.

## Decisión

La API no guarda nada entre peticiones. El navegador conserva el historial y lo manda en `history` en cada
`POST /ask`. El servidor solo carga al arrancar los datos de solo lectura (`employees.json`) y la configuración.
El historial se valida: roles `user` o `assistant` y contenido con el mismo largo máximo que la pregunta.

## Consecuencias

- Cualquier copia atiende cualquier petición; escalar es correr más procesos (`/health` devuelve el `pid`).
- Las peticiones crecen con la conversación y el cliente puede alterar el historial; por eso se valida y no
  da acceso a datos distintos de los de las herramientas.
- Recargar la página pierde la conversación; es aceptable en esta sesión.
