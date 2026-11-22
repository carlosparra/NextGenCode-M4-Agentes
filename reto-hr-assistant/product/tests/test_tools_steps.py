"""Pasos de ``features/tools.feature``: saldo de vacaciones y resumen por área.

Contrato que fijan estas pruebas (JSON en texto, como las herramientas existentes):

- ``get_vacation_balance``: ``name``, ``vacation_days_total``,
  ``vacation_days_taken`` y ``vacation_days_available``.
- ``department_summary``: ``employees``, ``active``, ``inactive`` y
  ``average_vacation_days_available`` (un decimal, ``null`` sin activos).
"""

import json

from pytest_bdd import given, parsers, scenarios, then, when

scenarios("features/tools.feature")


@given("the employee directory", target_fixture="employees")
def employee_directory(directory):
    """Directorio cargado desde los datos del producto."""
    return directory


@when(
    parsers.parse('I ask the vacation balance of "{employee_id}"'),
    target_fixture="tool_output",
)
def ask_vacation_balance(employees, employee_id):
    """Llama a ``get_vacation_balance`` con el id pedido."""
    return employees.get_vacation_balance(employee_id)


@when(
    parsers.parse('I ask the summary of the department "{department}"'),
    target_fixture="tool_output",
)
def ask_department_summary(employees, department):
    """Llama a ``department_summary`` con el departamento pedido."""
    return employees.department_summary(department)


@then(
    parsers.parse(
        'the balance of "{name}" shows {total:d} total days, {taken:d} taken '
        "and {available:d} available"
    )
)
def balance_is_calculated(tool_output, name, total, taken, available):
    """El saldo trae el nombre y los días calculados en código."""
    balance = json.loads(tool_output)
    assert balance["name"] == name
    assert balance["vacation_days_total"] == total
    assert balance["vacation_days_taken"] == taken
    assert balance["vacation_days_available"] == available


@then("the tool says the employee no longer has a vacation balance")
def no_balance_for_former_employee(tool_output):
    """Un empleado de baja no recibe números de saldo."""
    assert "ya no tiene saldo de vacaciones" in tool_output.casefold()


@then(
    parsers.parse('the message is the same one get_employee gives for "{employee_id}"')
)
def same_unknown_message(employees, tool_output, employee_id):
    """El id inexistente se reporta igual en ambas herramientas."""
    assert tool_output == employees.get_employee(employee_id)


@then(
    parsers.parse(
        "the summary shows {total:d} employees, {active:d} active "
        "and {inactive:d} inactive"
    )
)
def summary_counts(tool_output, total, active, inactive):
    """Los conteos del resumen salen del código."""
    summary = json.loads(tool_output)
    assert summary["employees"] == total
    assert summary["active"] == active
    assert summary["inactive"] == inactive


@then(
    parsers.parse(
        "the average available vacation days of the active employees is {average:f}"
    )
)
def summary_average(tool_output, average):
    """El promedio solo cuenta a las personas activas."""
    assert json.loads(tool_output)["average_vacation_days_available"] == average


@then("the tool lists every valid department")
def lists_valid_departments(employees, tool_output):
    """El mensaje nombra cada departamento que sí existe."""
    for department in employees.departments():
        assert department in tool_output
