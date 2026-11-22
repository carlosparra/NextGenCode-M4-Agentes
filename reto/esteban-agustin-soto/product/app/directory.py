"""Directorio de empleados de solo lectura."""

import json
import unicodedata
from pathlib import Path


def normalize(text):
    """Pasa a minúsculas y quita acentos para comparar.

    :param text: Texto original
    :type text: str
    :return: Texto sin acentos y en minúsculas
    :rtype: str
    """
    decomposed = unicodedata.normalize("NFD", text.strip().lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


class EmployeeDirectory:
    """Carga ``employees.json`` y ofrece consultas de solo lectura.

    :param path: Ruta del archivo de empleados
    :type path: str or pathlib.Path
    :raises FileNotFoundError: Si el archivo no existe
    :raises ValueError: Si el contenido no es una lista JSON válida
    """

    def __init__(self, path):
        with open(Path(path), encoding="utf-8") as handle:
            try:
                data = json.load(handle)
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid JSON in {path}") from error
        if not isinstance(data, list):
            raise ValueError("The employees file must contain a list")
        self._employees = tuple(data)

    def get_employee(self, employee_id):
        """Busca un empleado por id.

        :param employee_id: Id con forma ``EMP-0001``
        :type employee_id: str
        :return: El empleado o ``None`` si no existe
        :rtype: dict or None
        """
        wanted = str(employee_id).strip().upper()
        for employee in self._employees:
            if employee["id"].upper() == wanted:
                return dict(employee)
        return None

    def search_by_department(self, department):
        """Lista los empleados de un departamento.

        :param department: Nombre del departamento (sin importar acentos)
        :type department: str
        :return: Empleados encontrados (puede ser vacía)
        :rtype: list
        """
        wanted = normalize(str(department))
        return [
            dict(e) for e in self._employees
            if normalize(e["department"]) == wanted
        ]

    def departments(self):
        """Lista los departamentos existentes.

        :return: Nombres únicos de departamentos
        :rtype: list
        """
        names = []
        for employee in self._employees:
            if employee["department"] not in names:
                names.append(employee["department"])
        return names
