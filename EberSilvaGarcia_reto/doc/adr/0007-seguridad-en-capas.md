# 0007. Seguridad en capas y compliance como código

- Estado: aceptada
- Fecha: 2026-11-24

## Contexto

El asistente maneja datos de empleados, algunos personales (CURP, RFC, NSS, salario,
contacto). Un solo control no basta: una capa puede fallar.

## Decisión

Cada petición cruza capas independientes: identidad y permisos, límite, validación de
esquema, guardas de entrada (inyección, PII, datos protegidos), herramientas de solo
lectura y acotadas, minimización de datos en el dominio, verificación por código, guardas
de salida, auditoría y trazas sin texto. Con `ENVIRONMENT=production` el sistema se niega a
arrancar si la configuración es insegura (`app/config.py::check_compliance` y
`app/preflight.py`). Detalle en `doc/security.md` y `doc/compliance-checklist.md`.

## Consecuencias

- Cada control tiene su prueba automática.
- Las reglas de detección por expresiones regulares tienen falsos positivos y negativos;
  se documentan como limitación y como mejora (un clasificador dedicado).
