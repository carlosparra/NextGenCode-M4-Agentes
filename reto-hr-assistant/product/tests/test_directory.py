"""Pruebas unitarias del directorio de empleados (solo lectura)."""


def test_existing_employee_is_returned_with_readable_accents(directory):
    result = directory.get_employee("EMP-0004")

    assert "Jorge Díaz" in result
    assert "Tecnología" in result


def test_department_search_ignores_capitalization(directory):
    result = directory.search_by_department("FINANZAS")

    assert "Sofía Gómez" in result
    assert "Ana López" not in result
