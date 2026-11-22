# 0015. Filtro de la respuesta: HTML, PII, recorte y respaldo, en ese orden

Estado: propuesto

## Contexto

La respuesta del modelo no es confiable: puede traer PII, etiquetas HTML o ser demasiado larga. La página ya pinta con
`textContent`, pero el contrato de la API no debe depender de un solo cliente. El orden de los pasos cambia el
resultado: recortar antes de redactar puede dejar medio correo sin detectar, y una etiqueta puede partir un dato
(`ana<b>@</b>x.com`).

## Decisión

`app/output_filter.py` expone `clean_answer` y `main.py` la aplica a toda respuesta antes de armar `AskResponse`:
1) quitar etiquetas HTML, 2) redactar PII con `app/pii.py` (si `PII_REDACTION=true`), 3) recortar a
`MAX_ANSWER_CHARS`, 4) si queda vacía o solo espacios, responder «No tengo una respuesta para eso.» Si hubo PII se
emite `pii_detected` con `direction: "output"`. Los pasos 1, 3 y 4 se aplican siempre.

## Consecuencias

- Ningún cliente recibe HTML ni PII del modelo, aunque no use `textContent`.
- Un marcador puede quedar cortado al final del recorte; se acepta porque ya no contiene el dato.
- El texto de respaldo del agente (tope de vueltas) también pasa por el filtro sin cambios.
- Es una función pura y se prueba sin la API.
