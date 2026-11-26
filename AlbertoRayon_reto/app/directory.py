"""Directorio de empleados: solo lectura y solo campos públicos.

El archivo de datos trae datos personales ficticios (correo, teléfono, RFC). Este
módulo nunca los entrega: las herramientas de los agentes solo ven ``PUBLIC_FIELDS``.
"""

import json
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path

PUBLIC_FIELDS = ("id", "name", "department", "role", "start_date", "status")


class NotFoundError(LookupError):
    """El empleado o el departamento no existe."""


@dataclass(frozen=True)
class Employee:
    """Ficha pública de un empleado."""

    id: str
    name: str
    department: str
    role: str
    start_date: date
    status: str

    @property
    def active(self) -> bool:
        """Indica si el empleado sigue activo."""
        return self.status == "activo"

    def describe(self) -> str:
        """Texto de la ficha, como lo recibe el modelo.

        :return: Una línea con los campos públicos
        :rtype: str
        """
        return (
            f"{self.id}: {self.name}, {self.role}, departamento {self.department}, "
            f"ingreso {self.start_date.isoformat()}, estado {self.status}"
        )


def normalize(text: str) -> str:
    """Quita acentos y mayúsculas para comparar nombres.

    :param text: Texto original
    :type text: str
    :return: Texto en minúsculas y sin acentos
    :rtype: str
    """
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn").strip()


class Directory:
    """Empleados cargados de un archivo JSON."""

    def __init__(self, employees: list[Employee]):
        self._employees = {employee.id: employee for employee in employees}

    @classmethod
    def from_file(cls, path: Path) -> "Directory":
        """Carga el directorio y descarta los campos que no son públicos.

        :param path: Archivo JSON con la lista de empleados
        :type path: pathlib.Path
        :return: Directorio listo para consultar
        :rtype: Directory
        """
        records = json.loads(Path(path).read_text(encoding="utf-8"))
        employees = []
        for record in records:
            public = {name: record[name] for name in PUBLIC_FIELDS}
            public["start_date"] = date.fromisoformat(public["start_date"])
            employees.append(Employee(**public))
        return cls(employees)

    def get(self, employee_id: str) -> Employee:
        """Busca un empleado por id.

        :param employee_id: Id con la forma ``EMP-0001``
        :type employee_id: str
        :return: El empleado
        :rtype: Employee
        :raises NotFoundError: Si el id no existe
        """
        employee = self._employees.get(str(employee_id).strip().upper())
        if employee is None:
            raise NotFoundError(f"No existe el empleado {employee_id}.")
        return employee

    def departments(self) -> list[str]:
        """Nombres de los departamentos, en orden alfabético.

        :return: Departamentos que existen en los datos
        :rtype: list[str]
        """
        return sorted({employee.department for employee in self._employees.values()})

    def find_department(self, text: str) -> str | None:
        """Encuentra el departamento que menciona un texto.

        :param text: Pregunta o nombre de departamento
        :type text: str
        :return: El nombre oficial, o ``None`` si no menciona ninguno
        :rtype: str | None
        """
        plain = normalize(text)
        for department in self.departments():
            if normalize(department) in plain:
                return department
        return None

    def by_department(self, department: str) -> list[Employee]:
        """Empleados de un departamento.

        :param department: Nombre del departamento, con o sin acentos
        :type department: str
        :return: Sus empleados, ordenados por id
        :rtype: list[Employee]
        :raises NotFoundError: Si el departamento no existe
        """
        official = self.find_department(str(department))
        if official is None:
            raise NotFoundError(
                f"No existe el departamento {department}. "
                f"Departamentos: {', '.join(self.departments())}."
            )
        return sorted(
            (e for e in self._employees.values() if e.department == official),
            key=lambda employee: employee.id,
        )
