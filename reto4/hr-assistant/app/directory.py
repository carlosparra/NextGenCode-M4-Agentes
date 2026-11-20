"""Directorio de empleados de solo lectura y sus dos herramientas.

Un archivo de empleados inválido impide arrancar con :class:`ConfigError` y un
mensaje que nombra ``EMPLOYEES_PATH`` (ADR 0004).
"""

import json
from pathlib import Path

from app.config import ConfigError

REQUIRED_FIELDS = ("id", "name", "role", "department", "start_date", "status")


def _describe(employee):
    """Da formato de texto a un empleado.

    :param employee: Registro del empleado
    :type employee: dict
    :return: Descripción en una línea
    :rtype: str
    """
    return (
        f"{employee['id']} {employee['name']}, {employee['role']}, "
        f"departamento {employee['department']}, ingreso "
        f"{employee['start_date']}, estado {employee['status']}"
    )


class EmployeeDirectory:
    """Directorio de empleados en memoria, de solo lectura.

    :param employees: Registros de empleados
    :type employees: list[dict]
    """

    def __init__(self, employees):
        self._employees = tuple(dict(employee) for employee in employees)
        self._by_id = {employee["id"]: employee for employee in self._employees}

    def get_employee(self, employee_id):
        """Busca un empleado por id.

        :param employee_id: Id del empleado, por ejemplo ``EMP-0004``
        :type employee_id: str
        :return: Descripción del empleado o aviso de que no existe
        :rtype: str
        """
        key = str(employee_id).strip().upper()
        employee = self._by_id.get(key)
        if employee is None:
            return f"El empleado {key} no existe."
        return _describe(employee)

    def search_by_department(self, department):
        """Lista los empleados de un departamento.

        :param department: Nombre del departamento
        :type department: str
        :return: Lista de empleados o aviso de que no hay ninguno
        :rtype: str
        """
        wanted = str(department).strip().lower()
        found = [
            employee
            for employee in self._employees
            if employee["department"].lower() == wanted
        ]
        if not found:
            return f"No hay empleados en el departamento {department}."
        return "; ".join(_describe(employee) for employee in found)

    def departments(self):
        """Devuelve los departamentos sin duplicados, en orden de aparición.

        :return: Nombres de departamentos
        :rtype: list[str]
        """
        names = []
        for employee in self._employees:
            if employee["department"] not in names:
                names.append(employee["department"])
        return names


def _invalid_records(employees):
    """Devuelve las posiciones de los registros sin los campos de texto usados.

    :param employees: Registros leídos del archivo
    :type employees: list
    :return: Índices (desde 0) de los registros inválidos
    :rtype: list[int]
    """
    return [
        index
        for index, employee in enumerate(employees)
        if not isinstance(employee, dict)
        or not all(
            isinstance(employee.get(name), str) and employee[name].strip()
            for name in REQUIRED_FIELDS
        )
    ]


def load_directory(path):
    """Carga el directorio desde un archivo JSON.

    :param path: Ruta del archivo de empleados
    :type path: str or pathlib.Path
    :return: El directorio cargado
    :rtype: EmployeeDirectory
    :raises ConfigError: Si el archivo no existe, no es JSON, no es una lista o
        a algún registro le falta ``id``, ``name``, ``role``, ``department``,
        ``start_date`` o ``status``
    """
    try:
        with Path(path).open(encoding="utf-8") as handle:
            employees = json.load(handle)
    except (OSError, ValueError) as error:
        raise ConfigError(f"No se pudo leer EMPLOYEES_PATH ({path}).") from error
    if not isinstance(employees, list):
        raise ConfigError(
            f"EMPLOYEES_PATH ({path}) debe contener una lista de empleados."
        )
    invalid = _invalid_records(employees)
    if invalid:
        positions = ", ".join(str(index) for index in invalid)
        raise ConfigError(
            f"EMPLOYEES_PATH ({path}) tiene registros sin los campos "
            f"{', '.join(REQUIRED_FIELDS)}: posiciones {positions}."
        )
    return EmployeeDirectory(employees)
