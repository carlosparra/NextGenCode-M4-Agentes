# 0001. API sin estado con historial enviado por el cliente

Estado: propuesto

## Contexto

El HR Assistant debe escalar corriendo más copias del proceso detrás de un balanceador. Si la API guardara
conversaciones en memoria, cada copia tendría una vista distinta y haría falta afinidad de sesión o un almacén
compartido.

## Decisión

- La API no guarda nada entre peticiones. El navegador conserva el historial y lo envía en `history` en cada
  `POST /ask`.
- El agente y la lista de mensajes se crean por petición. Lo único compartido es el `EmployeeDirectory`, de
  solo lectura y cargado al arrancar.
- `GET /health` devuelve el `pid` para comprobar que distintas copias atienden sin perder contexto.

## Consecuencias

- Escalar es correr más copias; cualquier copia puede atender cualquier petición.
- El cliente controla el historial: se valida (roles permitidos, largo de cada mensaje) y no se confía en él.
- Cada petición reenvía todo el historial, lo que aumenta tokens de entrada en conversaciones largas.
- Cambiar los datos requiere reiniciar las copias.
