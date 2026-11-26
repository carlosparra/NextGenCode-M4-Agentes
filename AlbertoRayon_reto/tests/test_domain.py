"""Directorio y vacaciones: los números los decide el código."""

from datetime import date

import pytest

from app.config import load_settings
from app.directory import Directory, NotFoundError
from app.vacations import VacationLedger, entitlement_days, years_of_service

SETTINGS = load_settings({})
TODAY = date(2026, 11, 26)


@pytest.fixture
def directory():
    return Directory.from_file(SETTINGS.employees_path)


@pytest.fixture
def ledger():
    return VacationLedger.from_file(SETTINGS.vacations_path)


def test_directory_never_exposes_personal_fields(directory):
    employee = directory.get("emp-0001")
    assert not hasattr(employee, "email")
    assert "@" not in employee.describe()
    assert "LOAA" not in employee.describe()


def test_unknown_employee_raises_not_found(directory):
    with pytest.raises(NotFoundError, match="EMP-9999"):
        directory.get("EMP-9999")


def test_department_is_found_without_accents(directory):
    names = [person.name for person in directory.by_department("tecnologia")]
    assert names == ["Ana López", "Marta Ruiz", "Jorge Díaz"]


def test_unknown_department_lists_the_valid_ones(directory):
    with pytest.raises(NotFoundError, match="Finanzas"):
        directory.by_department("Legal")


@pytest.mark.parametrize("years, days", [
    (0, 0), (1, 12), (2, 14), (3, 16), (4, 18), (5, 20), (6, 22), (10, 22),
    (11, 24), (15, 24), (16, 26), (21, 28), (26, 30), (31, 32),
])
def test_entitlement_follows_the_lft_table(years, days):
    assert entitlement_days(years) == days


def test_years_of_service_count_only_completed_years():
    assert years_of_service(date(2022, 1, 10), date(2026, 1, 9)) == 3
    assert years_of_service(date(2022, 1, 10), date(2026, 1, 10)) == 4
    assert years_of_service(date(2027, 1, 1), TODAY) == 0
    assert years_of_service(date(2024, 2, 29), date(2025, 2, 28)) == 1


def test_balance_subtracts_days_taken_in_the_current_period(directory, ledger):
    balance = ledger.balance(directory.get("EMP-0004"), TODAY)
    # El registro de diciembre de 2025 es del periodo anterior y no cuenta
    assert (balance.entitled_days, balance.taken_days, balance.remaining_days) == (
        18, 6, 12
    )
    assert balance.period_start == "2026-01-10"
    assert "le quedan 12" in balance.describe()


def test_inactive_employee_has_no_balance(directory, ledger):
    balance = ledger.balance(directory.get("EMP-0003"), TODAY)
    assert not balance.eligible
    assert "baja" in balance.describe()


def test_first_year_generates_no_days(directory, ledger):
    balance = ledger.balance(directory.get("EMP-0004"), date(2022, 6, 1))
    assert not balance.eligible
    assert balance.as_dict()["entitled_days"] == 0
