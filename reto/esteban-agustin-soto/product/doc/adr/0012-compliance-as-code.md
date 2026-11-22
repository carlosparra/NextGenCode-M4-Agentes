# 0012. Compliance como código: negarse a arrancar

## Contexto
Una configuración insegura en producción (modelo simulado, claves débiles o trazas con datos de empleados) pasa inadvertida si solo está en un documento.

## Decisión
Con `ENVIRONMENT=production`, `compliance.py` revisa la configuración al construir la app y lanza un error si `MODEL_PROVIDER` es `fake`, si `API_KEYS` está vacía o tiene una clave de menos de 16 caracteres, o si las trazas están encendidas y `HIDE_INPUTS` o `HIDE_OUTPUTS` no valen `true`. `doc/compliance-checklist.md` lista cada regla, su lugar en el código y su prueba. En `development` no se aplica ninguna.

## Consecuencias
- Un despliegue mal configurado falla al arrancar y Render lo marca no sano (`/health`), en vez de quedar expuesto.
- Cada regla nueva exige código, prueba y fila en la tabla.
- Los mensajes dicen qué regla falló, nunca el valor de una clave.
