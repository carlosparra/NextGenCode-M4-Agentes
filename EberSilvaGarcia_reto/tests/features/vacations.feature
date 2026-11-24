# language: es
Característica: Saldo de vacaciones con un agente ReAct
  Como persona de Recursos Humanos
  Quiero saber cuántos días de vacaciones le quedan a un empleado
  Para aprobar solicitudes sin hacer cuentas a mano

  Escenario: Empleado activo con días tomados
    Dado el asistente con el modelo simulado al 24 de noviembre de 2026
    Cuando pregunto "¿Cuántas vacaciones le quedan a EMP-0004?"
    Entonces el agente usa la herramienta "vacation_balance"
    Y el saldo calculado es de 10 días
    Y el subagente razonó en 3 pasos

  Escenario: Empleada de baja
    Dado el asistente con el modelo simulado al 24 de noviembre de 2026
    Cuando pregunto "¿Cuántas vacaciones le quedan a EMP-0003?"
    Entonces el saldo calculado es de 0 días
