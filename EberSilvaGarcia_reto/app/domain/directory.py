"""Directorio de empleados de solo lectura.

Mínimo privilegio sobre los datos: el directorio carga los datos personales
(CURP, RFC, NSS, correo, teléfono, salario) pero **nunca los entrega**. Solo
expone la vista pública, con una lista blanca de campos.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path

EMPLOYEE_ID_PATTERN = re.compile(r"^EMP-\d{4}$")
PUBLIC_FIELDS = ("id", "name", "department", "role", "start_date", "status")
PROTECTED_FIELDS = ("curp", "rfc", "nss", "personal_email", "phone", "salary_mxn")


class NotFoundError(LookupError):
    """Lo pedido no existe (empleado o departamento).

    Su mensaje es apto para mostrarlo al usuario.
    """


def normalize(text: str) -> str:
    """Quita acentos y pasa a minúsculas para comparar textos.

    :param text: Texto original
    :type text: str
    :return: Texto normalizado
    :rtype: str
    """
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


@dataclass(frozen=True)
class Employee:
    """Vista pública de un empleado (sin datos personales)."""

    id: str
    name: str
    department: str
    role: str
    start_date: date
    status: str

    @property
    def is_active(self) -> bool:
        """Indica si el empleado sigue activo.

        :return: ``True`` si su estado es ``activo``
        :rtype: bool
        """
        return self.status == "activo"

    def public_dict(self) -> dict:
        """Diccionario con los campos públicos.

        :return: Campos de la lista blanca
        :rtype: dict
        """
        return {
            "id": self.id,
            "name": self.name,
            "department": self.department,
            "role": self.role,
            "start_date": self.start_date.isoformat(),
            "status": self.status,
        }


class Directory:
    """Consultas de solo lectura sobre los empleados.

    :param records: Registros crudos, como vienen del archivo
    :type records: list[dict]
    """

    def __init__(self, records: list[dict]) -> None:
        self._by_id: dict[str, Employee] = {}
        for record in records:
            employee = Employee(
                id=record["id"],
                name=record["name"],
                department=record["department"],
                role=record["role"],
                start_date=date.fromisoformat(record["start_date"]),
                status=record["status"],
            )
            self._by_id[employee.id] = employee

    @classmethod
    def from_file(cls, path: Path) -> "Directory":
        """Carga el directorio desde un archivo JSON.

        :param path: Ruta al archivo de empleados
        :type path: pathlib.Path
        :return: Directorio cargado
        :rtype: Directory
        """
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def get(self, employee_id: str) -> Employee | None:
        """Busca un empleado por id.

        :param employee_id: Id con forma ``EMP-0000``
        :type employee_id: str
        :return: El empleado, o ``None`` si no existe
        :rtype: Employee | None
        """
        return self._by_id.get(employee_id.strip().upper())

    def departments(self) -> list[str]:
        """Departamentos que existen en los datos.

        :return: Nombres ordenados
        :rtype: list[str]
        """
        return sorted({e.department for e in self._by_id.values()})

    def resolve_department(self, text: str) -> str | None:
        """Encuentra el departamento que menciona un texto.

        :param text: Texto libre, por ejemplo una pregunta
        :type text: str
        :return: Nombre oficial del departamento o ``None``
        :rtype: str | None
        """
        wanted = normalize(text)
        for name in sorted(self.departments(), key=len, reverse=True):
            if normalize(name) in wanted:
                return name
        return None

    def by_department(self, department: str) -> list[Employee]:
        """Empleados de un departamento.

        :param department: Nombre del departamento (sin importar acentos)
        :type department: str
        :return: Empleados ordenados por id
        :rtype: list[Employee]
        """
        wanted = normalize(department.strip())
        return sorted(
            (e for e in self._by_id.values() if normalize(e.department) == wanted),
            key=lambda e: e.id,
        )
