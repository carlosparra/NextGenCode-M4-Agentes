# 0008. Palabras clave del enrutador al inicio de una palabra

## Contexto

El enrutador (ADR 0007) busca las palabras clave como subcadena del texto normalizado. Así «métodos» contiene
«todos» y «presume» contiene «resume»: preguntas simples van al modelo caro y el costo sube sin mejorar la
calidad. A la vez, formas derivadas como «resumen», «explicación» o «analizar» sí piden el modelo capaz.

## Decisión

Después de normalizar (minúsculas, sin acentos), una palabra clave cuenta solo si empieza en un inicio de
palabra: expresión `\b<palabra>` sobre el texto normalizado. «por que» se trata como dos palabras seguidas
por espacios. El motivo sigue siendo `keyword:<palabra>`.

## Consecuencias

- Desaparecen los falsos positivos dentro de otras palabras; las formas derivadas siguen yendo al modelo capaz.
- La regla sigue siendo pura, gratis y explicable; se prueba con casos positivos y negativos en
  `test_router.py`.
- «porqué» escrito junto no dispara la regla; se acepta, porque la especificación pide «por qué».
