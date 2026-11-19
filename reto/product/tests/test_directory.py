"""Pruebas del directorio de empleados (solo lectura)."""


def test_unknown_employee_is_reported_with_its_id(directory):
    result = directory.get_employee("EMP-0099")

    assert "error" in result
    assert "EMP-0099" in result["error"]


def test_department_search_ignores_case_and_accents(directory):
    employees = directory.search_by_department("TECNOLOGIA")

    names = {employee["name"] for employee in employees}

    assert names == {"Ana López", "Marta Ruiz", "Jorge Díaz"}
