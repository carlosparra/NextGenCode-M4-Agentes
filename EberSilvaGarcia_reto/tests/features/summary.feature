# language: es
Característica: Resumen por área con un agente de reflexión
  Como gerente de Recursos Humanos
  Quiero un resumen fiel de cada área
  Para conocer su plantilla sin revisar registro por registro

  Escenario: El crítico obliga a corregir el borrador
    Dado el asistente con el modelo simulado al 24 de noviembre de 2026
    Cuando pido el resumen del área "Tecnología"
    Entonces el resumen menciona "5.5 años"
    Y hubo 1 vuelta de reflexión
    Y el resumen final fue aceptado por el crítico
