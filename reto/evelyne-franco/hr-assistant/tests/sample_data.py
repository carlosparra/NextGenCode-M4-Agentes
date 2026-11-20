"""Datos de muestra compartidos por las pruebas del HR Assistant.

Contiene los empleados de prueba y, desde la spec 06, una copia de
``spec/policies.json`` con las constantes del sistema multi-agente.
``tests.conftest`` los vuelve a exportar, asi que las pruebas pueden
seguir importandolos desde ahi.
"""

SAMPLE_EMPLOYEES = [
    {
        "id": "EMP-0001",
        "name": "Ana Lopez",
        "department": "Tecnologia",
        "role": "Analista de datos",
        "start_date": "2019-03-04",
        "status": "activo",
    },
    {
        "id": "EMP-0002",
        "name": "Luis Perez",
        "department": "Ventas",
        "role": "Ejecutivo de cuenta",
        "start_date": "2021-07-19",
        "status": "activo",
    },
    {
        "id": "EMP-0003",
        "name": "Marta Ruiz",
        "department": "Tecnologia",
        "role": "Desarrolladora",
        "start_date": "2016-11-02",
        "status": "baja",
    },
    {
        "id": "EMP-0004",
        "name": "Jorge Diaz",
        "department": "Tecnologia",
        "role": "Lider tecnico",
        "start_date": "2022-01-10",
        "status": "activo",
    },
    {
        "id": "EMP-0005",
        "name": "Sofia Gomez",
        "department": "Finanzas",
        "role": "Contadora",
        "start_date": "2020-05-25",
        "status": "activo",
    },
]

# Spec 06: copia de ``spec/policies.json`` (politicas de RH).
VACATION_TEXT = (
    "Vacaciones: el primer año de servicio corresponden 12 días hábiles; a "
    "partir del segundo año se suman 2 días por año hasta llegar a 20, y "
    "después 2 días más por cada 5 años. Se solicitan con al menos 15 días "
    "naturales de anticipación."
)
SAMPLE_POLICIES = [
    {
        "topic": "vacaciones",
        "keywords": ["vacaciones", "dias libres", "descanso anual"],
        "text": VACATION_TEXT,
    },
    {
        "topic": "prima vacacional",
        "keywords": ["prima vacacional", "prima de vacaciones"],
        "text": (
            "Prima vacacional: se paga el 25 % del salario correspondiente a "
            "los días de vacaciones, junto con el primer pago después de "
            "tomarlas."
        ),
    },
    {
        "topic": "aguinaldo",
        "keywords": ["aguinaldo"],
        "text": (
            "Aguinaldo: 15 días de salario, pagados a más tardar el 20 de "
            "diciembre. Si no se trabajó el año completo, se paga la parte "
            "proporcional."
        ),
    },
    {
        "topic": "home office",
        "keywords": [
            "home office",
            "trabajo remoto",
            "teletrabajo",
            "trabajo desde casa",
        ],
        "text": (
            "Home office: hasta 2 días por semana, acordados con el líder del "
            "equipo. El equipo de cómputo lo da la empresa y la conexión se "
            "apoya con 500 pesos al mes."
        ),
    },
    {
        "topic": "permisos",
        "keywords": ["permiso", "permisos", "paternidad", "maternidad"],
        "text": (
            "Permisos: maternidad de 84 días y paternidad de 5 días laborables, "
            "ambos con goce de sueldo. Hasta 3 días al año por asuntos "
            "personales con aviso previo al líder."
        ),
    },
    {
        "topic": "horario",
        "keywords": ["horario", "jornada", "hora de entrada", "hora de salida"],
        "text": (
            "Horario: jornada de 40 horas a la semana, de lunes a viernes. La "
            "entrada es flexible entre las 8 y las 10 de la mañana."
        ),
    },
]
POLICY_TOPICS = [policy["topic"] for policy in SAMPLE_POLICIES]
DIRECTORY_UNVERIFIED = (
    "No pude verificar la respuesta con el directorio. Intenta de nuevo."
)
POLICY_UNVERIFIED = (
    "No pude verificar la respuesta con las políticas. Intenta de nuevo."
)
AGENTS_DIRECTORY = ["guard", "supervisor", "directory", "reviewer"]
AGENTS_POLICY = ["guard", "supervisor", "policy", "reviewer"]
SUPERVISOR_INPUT_TOKENS = 7
SUPERVISOR_OUTPUT_TOKENS = 3

# Adenda 1 de la spec 06: notas de ``vacation_days`` y frase de A5 para
# EMP-0004 con el reloj en 2026-11-19 (4 años de servicio, 18 días).
FIRST_YEAR_NOTE = (
    "Aún no cumple su primer año; al cumplirlo le corresponden 12 días hábiles."
)
INACTIVE_NOTE = "El empleado no está activo."
# Resultado esperado de ``vacation_days("EMP-0004")`` en esa fecha.
JORGE_RESULT = {
    "employee_id": "EMP-0004",
    "name": "Jorge Diaz",
    "start_date": "2022-01-10",
    "status": "activo",
    "years_of_service": 4,
    "days": 18,
    "note": "",
}
JORGE_SENTENCE = (
    "Jorge Diaz (EMP-0004) tiene 4 años de servicio y le corresponden 18 días "
    "hábiles de vacaciones."
)

# Spec 06, punto 7: contadores de rutas del supervisor, todos en cero.
SUPERVISOR_ROUTES_AT_ZERO = {
    "rule:employee": 0,
    "rule:department": 0,
    "rule:policy": 0,
    # Adenda 1: nueva regla, id de empleado y tema de vacaciones.
    "rule:policy_employee": 0,
    "model": 0,
    "model_invalid": 0,
}
