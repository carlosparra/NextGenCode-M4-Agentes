"""Directorio de empleados de solo lectura cargado desde un archivo JSON."""

import json
import unicodedata
from pathlib import Path


class DirectoryError(ValueError):
    """Error al cargar el archivo de empleados."""


def normalize_text(text: str) -> str:
    """Normaliza un texto para compararlo sin mayusculas ni acentos.

    :param text: Texto original
    :type text: str
    :return: Texto en minusculas (``casefold``) y sin acentos
    :rtype: str
    """
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


class EmployeeDirectory:
    """Directorio inmutable de empleados.

    El archivo se lee una sola vez al construir el objeto.

    :param path: Ruta al archivo ``employees.json``
    :type path: pathlib.Path or str
    :raises DirectoryError: Si el archivo no se puede leer o no es valido
    """

    def __init__(self, path):
        self._employees = tuple(self._load(Path(path)))

    @staticmethod
    def _load(path: Path) -> list:
        """Lee y valida el archivo de empleados.

        :param path: Ruta al archivo
        :type path: pathlib.Path
        :return: Lista de empleados
        :rtype: list[dict]
        :raises DirectoryError: Si el archivo no existe o su contenido es invalido
        """
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            message = f"Cannot load employees file {path}: {error}"
            raise DirectoryError(message) from error
        if not isinstance(data, list) or not all(
            isinstance(item, dict) and "id" in item for item in data
        ):
            raise DirectoryError(
                f"Employees file {path} must be a list of objects with an id"
            )
        return data

    def get_employee(self, employee_id: str) -> dict:
        """Busca un empleado por id.

        :param employee_id: Id del empleado, por ejemplo ``EMP-0004``
        :type employee_id: str
        :return: Copia de los datos del empleado o ``{"error": ...}`` si no existe
        :rtype: dict
        """
        wanted = str(employee_id).strip().upper()
        for employee in self._employees:
            if str(employee["id"]).upper() == wanted:
                return dict(employee)
        return {"error": f"No existe un empleado con id {wanted}."}

    def search_by_department(self, department: str) -> list:
        """Lista los empleados de un departamento.

        La comparacion ignora mayusculas y acentos.

        :param department: Nombre del departamento
        :type department: str
        :return: Copias de los empleados del departamento (puede estar vacia)
        :rtype: list[dict]
        """
        wanted = normalize_text(str(department).strip())
        return [
            dict(employee)
            for employee in self._employees
            if normalize_text(str(employee.get("department", ""))) == wanted
        ]

    def departments(self) -> list:
        """Devuelve los departamentos existentes, sin repetir.

        :return: Nombres de los departamentos
        :rtype: list[str]
        """
        names = []
        for employee in self._employees:
            name = employee.get("department")
            if isinstance(name, str) and name not in names:
                names.append(name)
        return names
