"""Pruebas unitarias del directorio de empleados (``app.directory``)."""

import json

import pytest

from app.config import ConfigError
from app.directory import load_directory

VALID_EMPLOYEE = {
    "id": "EMP-0001",
    "name": "Ana López",
    "role": "Analista",
    "department": "Finanzas",
    "start_date": "2020-01-15",
    "status": "activo",
}


def _write(tmp_path, content):
    """Escribe ``content`` en un archivo temporal y devuelve su ruta.

    :param tmp_path: Carpeta temporal de pytest
    :type tmp_path: pathlib.Path
    :param content: Texto del archivo
    :type content: str
    :return: Ruta del archivo escrito
    :rtype: pathlib.Path
    """
    path = tmp_path / "employees.json"
    path.write_text(content, encoding="utf-8")
    return path


def test_unknown_employee_is_reported(directory):
    text = directory.get_employee("EMP-9999")

    assert "EMP-9999" in text
    assert "no existe" in text


def test_department_lists_only_its_employees(directory):
    text = directory.search_by_department("Ventas")

    assert "Luis Pérez" in text
    assert "Ana López" not in text


def test_departments_are_listed_once(directory):
    departments = list(directory.departments())

    assert sorted(departments) == ["Finanzas", "Tecnología", "Ventas"]


def test_missing_employees_file_names_the_variable(tmp_path):
    with pytest.raises(ConfigError, match="EMPLOYEES_PATH"):
        load_directory(tmp_path / "does-not-exist.json")


def test_employees_file_that_is_not_json_names_the_variable(tmp_path):
    path = _write(tmp_path, "this is not json")

    with pytest.raises(ConfigError, match="EMPLOYEES_PATH"):
        load_directory(path)


def test_employees_file_that_is_not_a_list_names_the_variable(tmp_path):
    path = _write(tmp_path, json.dumps({"employees": [VALID_EMPLOYEE]}))

    with pytest.raises(ConfigError, match="EMPLOYEES_PATH"):
        load_directory(path)


@pytest.mark.parametrize(
    "field", ["id", "name", "role", "department", "start_date", "status"]
)
def test_employee_without_a_required_field_names_the_variable(tmp_path, field):
    employee = {key: value for key, value in VALID_EMPLOYEE.items() if key != field}
    path = _write(tmp_path, json.dumps([VALID_EMPLOYEE, employee]))

    with pytest.raises(ConfigError, match="EMPLOYEES_PATH"):
        load_directory(path)


def test_employee_with_a_blank_field_names_the_variable(tmp_path):
    employee = {**VALID_EMPLOYEE, "department": "   "}
    path = _write(tmp_path, json.dumps([employee]))

    with pytest.raises(ConfigError, match="EMPLOYEES_PATH"):
        load_directory(path)
