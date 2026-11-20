# 0012. Enmascarado de PII en la pregunta, el historial y la respuesta

## Contexto

El personal de RH puede escribir datos sensibles en la pregunta o en el historial (correo, CURP, RFC, tarjeta, NSS,
teléfono). Sin filtro, esos valores llegan al proveedor del modelo (ADR 0006) y a las trazas de LangSmith, y el modelo
podría devolverlos en la respuesta. La persona aprobó incorporar este paso aunque no estaba en `spec/` ni en el plan.

## Decisión

- `app/pii.py` expone `mask_pii(text) -> (texto, Counter)`. Usa expresiones regulares de la biblioteca estándar: no
  añade dependencias, es determinista y se prueba sin red. Cada valor se reemplaza por `[<tipo> oculto]`
  (`MASK_TEMPLATE`), con el tipo en inglés: `email`, `curp`, `rfc`, `card`, `nss` o `phone`.
- Los patrones se aplican en ese orden (`PII_PATTERNS`): CURP antes que RFC, porque comparten el inicio, y tarjeta
  antes que NSS y teléfono, porque una tarjeta contiene secuencias de esos largos. CURP y RFC no distinguen
  mayúsculas.
- En `POST /ask`, `main.py` enmascara la pregunta y el contenido de cada mensaje del historial antes de `agent.run`,
  y enmascara `result.answer` antes de responder. El enrutador (`choose_model`) recibe la pregunta original; ese
  texto no sale del proceso ni se registra.
- No se enmascara la salida de las herramientas (`get_employee`, `search_by_department`): `data/employees.json` no
  tiene campos de esos tipos, y si el modelo repite uno en la respuesta, el enmascarado de salida lo oculta.
- `_log_pii` registra un evento `audit` con `action: "pii_masked"`, `client`, `input` y `output`: diccionarios de
  tipo a conteo, nunca los valores. Solo se emite si se encontró algo. Esto amplía el contrato de `audit` de
  `spec/02-observability.md`, que solo preveía `action: "tool_call"` (ver nota en el ADR 0005).

## Consecuencias

- Ningún valor de esos tipos escrito por el usuario llega al proveedor, a las trazas ni a la respuesta.
- Falsos positivos aceptados: cualquier secuencia de 11 dígitos se toma como NSS, y cualquier secuencia de 10
  dígitos (con espacios o guiones, y `+52` opcional) se toma como teléfono. Un número largo legítimo se oculta. Los
  ids `EMP-0003` y las fechas `2019-03-04` no se ven afectados (`test_pii.py`).
- Falsos negativos posibles: formatos fuera de los patrones (teléfonos de otros países, correos con dominios raros).
  No es una garantía de anonimización completa.
- Quien lea `audit` debe filtrar por `action`: ya no todo `audit` es una llamada a herramienta.
- Si se agrega un tipo, se agrega en `PII_PATTERNS` respetando el orden, en `test_pii.py` y en el README.
