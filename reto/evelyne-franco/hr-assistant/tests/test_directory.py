"""Pruebas unitarias del modulo de directorio de empleados.

Verifica las herramientas de consulta ``get_employee`` y
``search_by_department`` con los datos de prueba de
``conftest.py`` (fixture ``directory``).
"""

import pytest

from app.directory import Directory


def test_existing_employee_returns_data(directory):
    """Un id valido devuelve los datos del empleado."""
    result = directory.get_employee("EMP-0001")
    assert "Ana Lopez" in str(result)


def test_unknown_employee_is_reported(directory):
    """Un id inexistente devuelve un mensaje informativo."""
    result = directory.get_employee("EMP-9999")
    text = str(result).lower()
    assert "no" in text or "not" in text


def test_existing_department_returns_list(directory):
    """Un departamento valido devuelve sus empleados."""
    result = directory.search_by_department("Finanzas")
    assert "Sofia Gomez" in str(result)


def test_missing_file_raises_error(tmp_path):
    """Un archivo inexistente impide la carga."""
    bad_path = str(tmp_path / "missing.json")
    with pytest.raises((FileNotFoundError, Exception)):
        Directory(bad_path)
