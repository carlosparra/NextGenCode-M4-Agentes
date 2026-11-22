"""Directorio de empleados de solo lectura con herramientas de mínimo privilegio.

Cada herramienta arma su salida solo con su lista explícita de campos
permitidos (ADR 0014): un campo nuevo en los datos no aparece en ninguna
respuesta hasta que alguien lo agregue a la lista correspondiente.
"""

import json
import unicodedata
from pathlib import Path

from app.config import ConfigError

EMPLOYEE_FIELDS = ("id", "name", "department", "role", "start_date", "status")
VACATION_FIELDS = ("name", "vacation_days_total", "vacation_days_taken")
STATUS_ACTIVE = "activo"
STATUS_INACTIVE = "baja"


def _load_employees(path) -> tuple[dict, ...]:
    """Lee y valida el archivo de empleados.

    :param path: Ruta al archivo JSON con la lista de empleados
    :type path: str or pathlib.Path
    :return: Empleados como diccionarios
    :rtype: tuple[dict, ...]
    :raises app.config.ConfigError: Si el archivo no existe, no es JSON válido o
        no es una lista de objetos
    """
    try:
        employees = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ConfigError(f"EMPLOYEES_PATH cannot be read: {path}") from error
    if not isinstance(employees, list) or not all(
        isinstance(employee, dict) for employee in employees
    ):
        raise ConfigError(f"EMPLOYEES_PATH must be a list of objects: {path}")
    return tuple(dict(employee) for employee in employees)


def normalize(text) -> str:
    """Normaliza un texto para compararlo sin mayúsculas ni acentos.

    :param text: Texto a normalizar
    :type text: str
    :return: Texto sin acentos, en minúsculas y sin espacios en los extremos
    :rtype: str
    """
    decomposed = unicodedata.normalize("NFKD", str(text).strip())
    without_marks = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    return without_marks.casefold()


def _pick(employee: dict, fields: tuple[str, ...]) -> dict:
    """Copia de un empleado solo los campos permitidos.

    :param employee: Registro completo del empleado
    :type employee: dict
    :param fields: Campos permitidos, en orden
    :type fields: tuple[str, ...]
    :return: Diccionario con los campos permitidos que existan
    :rtype: dict
    """
    return {name: employee[name] for name in fields if name in employee}


def _available_days(employee: dict) -> int:
    """Calcula en código los días de vacaciones disponibles.

    :param employee: Registro completo del empleado
    :type employee: dict
    :return: ``vacation_days_total - vacation_days_taken``
    :rtype: int
    """
    total = int(employee.get("vacation_days_total", 0))
    taken = int(employee.get("vacation_days_taken", 0))
    return total - taken


class EmployeeDirectory:
    """Carga los empleados una sola vez y ofrece consultas de solo lectura.

    :param path: Ruta al archivo JSON con la lista de empleados
    :type path: str or pathlib.Path
    :raises app.config.ConfigError: Si el archivo de empleados no es válido
    """

    def __init__(self, path):
        self._employees = _load_employees(path)

    def _find(self, employee_id) -> dict | None:
        """Busca el registro completo de un empleado por su id.

        :param employee_id: Id del empleado, por ejemplo ``EMP-0004``
        :type employee_id: str
        :return: El registro o ``None`` si no existe
        :rtype: dict or None
        """
        wanted = str(employee_id).strip().upper()
        for employee in self._employees:
            if str(employee.get("id", "")).upper() == wanted:
                return employee
        return None

    def _in_department(self, department) -> list[dict]:
        """Devuelve los registros de un departamento sin mayúsculas ni acentos.

        :param department: Nombre del departamento
        :type department: str
        :return: Registros completos del departamento
        :rtype: list[dict]
        """
        wanted = normalize(department)
        return [
            employee
            for employee in self._employees
            if normalize(employee.get("department", "")) == wanted
        ]

    @staticmethod
    def _unknown_employee(employee_id) -> str:
        """Mensaje para un id inexistente, igual en todas las herramientas.

        :param employee_id: Id pedido
        :type employee_id: str
        :return: Mensaje en español
        :rtype: str
        """
        return f"No existe ningún empleado con id {employee_id}."

    def get_employee(self, employee_id: str) -> str:
        """Busca un empleado por su id y devuelve solo sus campos permitidos.

        :param employee_id: Id del empleado, por ejemplo ``EMP-0004``
        :type employee_id: str
        :return: El empleado como texto JSON o un mensaje si no existe
        :rtype: str
        """
        employee = self._find(employee_id)
        if employee is None:
            return self._unknown_employee(employee_id)
        return json.dumps(_pick(employee, EMPLOYEE_FIELDS), ensure_ascii=False)

    def search_by_department(self, department: str) -> str:
        """Lista los empleados de un departamento (sin mayúsculas ni acentos).

        :param department: Nombre del departamento
        :type department: str
        :return: Lista de empleados como texto JSON o un mensaje si no hay
        :rtype: str
        """
        found = [
            _pick(employee, EMPLOYEE_FIELDS)
            for employee in self._in_department(department)
        ]
        if not found:
            return f"No hay empleados en el departamento {department}."
        return json.dumps(found, ensure_ascii=False)

    def get_vacation_balance(self, employee_id: str) -> str:
        """Devuelve el saldo de vacaciones de un empleado, calculado en código.

        :param employee_id: Id del empleado, por ejemplo ``EMP-0004``
        :type employee_id: str
        :return: Nombre, días totales, tomados y disponibles como texto JSON, o
            un mensaje si no existe o está de baja
        :rtype: str
        """
        employee = self._find(employee_id)
        if employee is None:
            return self._unknown_employee(employee_id)
        if employee.get("status") == STATUS_INACTIVE:
            name = employee.get("name", employee_id)
            return f"{name} está de baja y ya no tiene saldo de vacaciones."
        balance = _pick(employee, VACATION_FIELDS)
        balance["vacation_days_available"] = _available_days(employee)
        return json.dumps(balance, ensure_ascii=False)

    def department_summary(self, department: str) -> str:
        """Resume un departamento con conteos y promedio calculados en código.

        :param department: Nombre del departamento (sin mayúsculas ni acentos)
        :type department: str
        :return: Personas, activas, de baja y promedio de días disponibles de las
            activas (un decimal o ``null``) como texto JSON, o un mensaje con los
            departamentos válidos si no existe
        :rtype: str
        """
        members = self._in_department(department)
        if not members:
            valid = ", ".join(self.departments())
            return (
                f"No existe el departamento {department}. "
                f"Departamentos válidos: {valid}."
            )
        active = [e for e in members if e.get("status") == STATUS_ACTIVE]
        inactive = [e for e in members if e.get("status") == STATUS_INACTIVE]
        average = None
        if active:
            days = [_available_days(employee) for employee in active]
            average = round(sum(days) / len(days), 1)
        summary = {
            "department": members[0].get("department", department),
            "employees": len(members),
            "active": len(active),
            "inactive": len(inactive),
            "average_vacation_days_available": average,
        }
        return json.dumps(summary, ensure_ascii=False)

    def departments(self) -> list[str]:
        """Devuelve los departamentos sin duplicados, en orden de aparición.

        :return: Nombres de departamentos
        :rtype: list[str]
        """
        names = []
        for employee in self._employees:
            name = employee.get("department")
            if name and name not in names:
                names.append(name)
        return names
