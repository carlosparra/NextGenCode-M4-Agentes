# 0001. API sin estado

## Contexto

El HR Assistant debe escalar corriendo más copias del proceso. Si la API guardara conversaciones en memoria,
cada copia tendría un estado distinto y harían falta sesiones fijas o un almacén compartido.

## Decisión

La API FastAPI no guarda nada entre peticiones. El navegador conserva el historial y lo envía en `history`
en cada `POST /ask`. El directorio de empleados se carga al arrancar y es de solo lectura.

## Consecuencias

- Escalar es correr más copias; cualquier copia atiende cualquier petición (`/health` expone el `pid` para comprobarlo).
- Las peticiones crecen con el historial; `MAX_QUESTION_CHARS` limita la pregunta, pero no el historial completo.
- El cliente puede alterar su historial; no es un riesgo de seguridad porque las herramientas son de solo lectura.
