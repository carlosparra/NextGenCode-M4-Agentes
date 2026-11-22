"""Unit tests for app.directory."""

import pytest

from app.directory import EmployeeDirectory


def test_existing_employee_is_found(directory):
    employee = directory.get_employee("EMP-0004")
    assert employee["name"] == "Jorge Diaz"


def test_unknown_employee_is_reported_as_missing(directory):
    assert directory.get_employee("EMP-9999") is None


def test_department_search_ignores_case_and_accents(directory):
    names = {e["name"] for e in directory.search_by_department("tecnologia")}
    assert names == {"Ana Lopez", "Marta Ruiz", "Jorge Diaz"}
    assert directory.search_by_department("Marketing") == []
    assert sorted(directory.departments()) == [
        "Finanzas", "Tecnología", "Ventas",
    ]


def test_missing_data_file_fails_at_startup(tmp_path):
    with pytest.raises((FileNotFoundError, ValueError)):
        EmployeeDirectory(tmp_path / "nope.json")
