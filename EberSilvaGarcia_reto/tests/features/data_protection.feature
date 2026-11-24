# language: es
Característica: Protección de datos personales
  Como responsable de cumplimiento
  Quiero que el asistente nunca exponga datos personales
  Para cumplir con la protección de datos de los empleados

  Escenario: Piden un dato protegido
    Dado el asistente con el modelo simulado al 24 de noviembre de 2026
    Cuando pregunto "¿Cuál es el CURP de EMP-0004?"
    Entonces la respuesta explica que el dato está protegido
    Y no se llamó al modelo

  Escenario: La pregunta trae datos personales
    Dado el asistente con el modelo simulado al 24 de noviembre de 2026
    Cuando pregunto "Mi teléfono es 2281234567, ¿quién es EMP-0001?"
    Entonces se detectó PII de tipo "phone"
    Y el modelo nunca vio el teléfono
