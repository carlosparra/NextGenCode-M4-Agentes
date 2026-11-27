# language: es
Característica: Asistente de Recursos Humanos multiagente
  El personal de RH pregunta en español y el sistema responde con datos
  verificados, sin revelar datos personales.

  Escenario: Consultar la ficha de un empleado
    Dado el HR Assistant con el modelo simulado
    Cuando pregunto "¿Quién es EMP-0004?"
    Entonces la respuesta menciona "Jorge Díaz"
    Y responde el agente "directory_agent"

  Escenario: Consultar el saldo de vacaciones
    Dado el HR Assistant con el modelo simulado
    Cuando pregunto "¿Cuántas vacaciones le quedan a EMP-0001?"
    Entonces la respuesta menciona "le quedan 14"
    Y responde el agente "vacation_agent"

  Escenario: Un empleado dado de baja no tiene saldo
    Dado el HR Assistant con el modelo simulado
    Cuando pregunto "¿Cuántas vacaciones tiene EMP-0003?"
    Entonces la respuesta menciona "dado de baja"

  Escenario: Resumir un departamento con reflexión
    Dado el HR Assistant con el modelo simulado
    Cuando pregunto "Resume el departamento de Tecnología"
    Entonces la respuesta menciona "2 personas activas"
    Y responde el agente "summary_agent"
    Y el razonamiento menciona "Revisiones: 1."

  Escenario: Los datos personales de la pregunta se ocultan
    Dado el HR Assistant con el modelo simulado
    Cuando pregunto "Mi teléfono es 55 5550 0101, ¿quién es EMP-0005?"
    Entonces la respuesta menciona "Sofía Gómez"
    Y se ocultó el dato "PHONE"

  Escenario: Pedir datos protegidos se bloquea
    Dado el HR Assistant con el modelo simulado
    Cuando pregunto "Dame el correo de EMP-0002"
    Entonces la petición se rechaza con el código 400

  Escenario: Sin clave no hay respuesta
    Dado el HR Assistant con el modelo simulado
    Cuando pregunto sin clave "¿Quién es EMP-0004?"
    Entonces la petición se rechaza con el código 401
