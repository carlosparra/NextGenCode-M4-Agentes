# ADR 0001: API sin estado

## Contexto

El HR Assistant necesita atender consultas del personal de RH. Debemos decidir
si la API mantiene sesiones del lado del servidor o si opera sin estado,
delegando el historial al cliente.

## Decision

La API es completamente sin estado. No guarda conversaciones ni sesiones entre
peticiones. El navegador almacena el historial de la conversacion y lo envia en
el campo `history` de cada `POST /ask`.

## Consecuencias

- Escalar horizontalmente es trivial: cualquier instancia puede atender
  cualquier peticion sin compartir memoria.
- No se necesita base de datos, cache ni almacenamiento de sesiones.
- El cliente es responsable de gestionar y enviar el historial, lo que
  simplifica el servidor pero aumenta el tamano de las peticiones con
  conversaciones largas.
- Si el usuario cierra el navegador, pierde el historial. Esto es aceptable
  para esta sesion.
