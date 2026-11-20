"""Directorio de empleados del HR Assistant.

Carga ``employees.json`` y expone las herramientas de consulta
``get_employee`` y ``search_by_department``.

:seealso: Especificacion en ``spec/01-architecture.md``
"""

from __future__ import annotations

import json
from typing import Any

from app.text import fold_text


class Directory:
    """Directorio de empleados cargado desde un archivo JSON.

    Valida el archivo al cargarse; si falla, la aplicacion no
    arranca y muestra un error claro.

    :param path: Ruta al archivo JSON de empleados.
    :type path: str
    :raises FileNotFoundError: Si el archivo no existe.
    :raises ValueError: Si el JSON no es una lista valida.
    """

    def __init__(self, path: str) -> None:
        """Inicializa el directorio cargando el archivo.

        :param path: Ruta al archivo JSON de empleados.
        :type path: str
        """
        self._employees: list[dict[str, Any]] = []
        self._load(path)

    def _load(self, path: str) -> None:
        """Carga y valida el archivo de empleados.

        :param path: Ruta al archivo JSON.
        :type path: str
        :raises FileNotFoundError: Si el archivo no existe.
        :raises ValueError: Si el contenido no es una lista.
        """
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError(
                f"Se esperaba una lista en {path}, "
                f"se encontro {type(data).__name__}"
            )
        self._employees = data

    @property
    def departments(self) -> list[str]:
        """Lista de departamentos unicos en el directorio.

        :return: Nombres de departamentos sin duplicados.
        :rtype: list[str]
        """
        return list(
            {e["department"] for e in self._employees}
        )

    @property
    def ids(self) -> list[str]:
        """Ids de todos los empleados; los usa el revisor (spec 06).

        :return: Ids en el orden del archivo.
        :rtype: list[str]
        """
        return [str(e["id"]) for e in self._employees]

    def find(self, employee_id: str) -> dict[str, Any] | None:
        """Busca un empleado por id exacto (Adenda 1, ``vacation_days``).

        :param employee_id: Id ``EMP-dddd``.
        :type employee_id: str
        :return: Copia de los datos del empleado o ``None``.
        :rtype: dict[str, Any] | None
        """
        for emp in self._employees:
            if emp.get("id") == employee_id:
                return dict(emp)
        return None

    def get_employee(
        self, employee_id: str
    ) -> dict[str, Any] | str:
        """Busca un empleado por su identificador.

        :param employee_id: Identificador del empleado
            (p.ej. ``EMP-0001``).
        :type employee_id: str
        :return: Datos del empleado o mensaje informativo
            si no existe.
        :rtype: dict[str, Any] | str
        """
        for emp in self._employees:
            if emp["id"] == employee_id:
                return emp
        return (
            f"No se encontro ningun empleado con id "
            f"{employee_id}."
        )

    def search_by_department(
        self, department: str
    ) -> list[dict[str, Any]] | str:
        """Busca empleados de un departamento.

        :param department: Nombre del departamento.
        :type department: str
        :return: Lista de empleados o mensaje informativo
            si el departamento no existe.
        :rtype: list[dict[str, Any]] | str
        """
        # Se compara sin acentos: "Tecnologia" encuentra "Tecnología".
        wanted = fold_text(department)
        results = [
            e
            for e in self._employees
            if fold_text(e["department"]) == wanted
        ]
        if results:
            return results
        return (
            f"No se encontraron empleados en el "
            f"departamento {department}."
        )
