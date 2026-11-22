"""Pruebas de mínimo privilegio: cada herramienta da solo sus campos permitidos."""

import json

from app.directory import EmployeeDirectory

ALLOWED_EMPLOYEE_FIELDS = {"id", "name", "department", "role", "start_date", "status"}


def _all_tool_outputs(directory):
    """Corre las cuatro herramientas sobre cada empleado y departamento.

    :return: Textos devueltos por las herramientas
    :rtype: list[str]
    """
    outputs = []
    for department in directory.departments():
        outputs.append(directory.search_by_department(department))
        outputs.append(directory.department_summary(department))
        for employee in json.loads(directory.search_by_department(department)):
            outputs.append(directory.get_employee(employee["id"]))
            outputs.append(directory.get_vacation_balance(employee["id"]))
    return outputs


def _write_employees(tmp_path, employees):
    """Guarda empleados de prueba y devuelve su directorio.

    :rtype: app.directory.EmployeeDirectory
    """
    path = tmp_path / "employees.json"
    path.write_text(json.dumps(employees, ensure_ascii=False), encoding="utf-8")
    return EmployeeDirectory(path)


def _employee(employee_id, status, **extra):
    """Arma un empleado mínimo de Ventas.

    :rtype: dict
    """
    return {
        "id": employee_id,
        "name": f"Persona {employee_id}",
        "department": "Ventas",
        "role": "Ejecutivo",
        "start_date": "2020-01-01",
        "status": status,
        "vacation_days_total": 10,
        "vacation_days_taken": 2,
        **extra,
    }


def test_no_tool_ever_returns_personal_contact_data(directory):
    outputs = _all_tool_outputs(directory)

    assert len(outputs) > 0
    for output in outputs:
        assert "personal_email" not in output
        assert "personal_phone" not in output
        assert "@example.com" not in output
        assert "+52" not in output


def test_a_new_data_field_does_not_appear_until_it_is_allowed(tmp_path):
    directory = _write_employees(
        tmp_path, [_employee("EMP-0100", "activo", salary=999999)]
    )

    employee = json.loads(directory.get_employee("EMP-0100"))

    assert set(employee) == ALLOWED_EMPLOYEE_FIELDS
    for output in _all_tool_outputs(directory):
        assert "salary" not in output
        assert "999999" not in output


def test_department_without_active_people_has_no_average(tmp_path):
    directory = _write_employees(
        tmp_path, [_employee("EMP-0101", "baja"), _employee("EMP-0102", "baja")]
    )

    summary = json.loads(directory.department_summary("VENTAS"))

    assert (summary["employees"], summary["active"], summary["inactive"]) == (2, 0, 2)
    assert summary["average_vacation_days_available"] is None
