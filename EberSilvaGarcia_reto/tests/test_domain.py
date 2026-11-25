"""Reglas de negocio puras: directorio, vacaciones (LFT) y hechos por área."""

from datetime import date

import pytest

from app.config import load_settings
from app.domain.departments import department_facts
from app.domain.directory import Directory, normalize
from app.domain.vacations import (
    VacationLedger,
    anniversary,
    current_period,
    entitled_days,
    years_between,
)

SETTINGS = load_settings({})


@pytest.fixture
def directory():
    return Directory.from_file(SETTINGS.employees_path)


@pytest.mark.parametrize(
    "years,days",
    [
        (0, 0),
        (1, 12),
        (2, 14),
        (3, 16),
        (4, 18),
        (5, 20),
        (6, 22),
        (10, 22),
        (11, 24),
        (15, 24),
        (16, 26),
        (21, 28),
        (26, 30),
        (31, 32),
    ],
)
def test_entitled_days_follow_article_76(years, days):
    assert entitled_days(years) == days


def test_years_between_counts_full_years():
    assert years_between(date(2020, 5, 25), date(2026, 5, 24)) == 5
    assert years_between(date(2020, 5, 25), date(2026, 5, 25)) == 6
    assert years_between(date(2027, 1, 1), date(2026, 1, 1)) == 0


def test_leap_day_anniversary_moves_to_the_28th():
    assert anniversary(date(2020, 2, 29), 2023) == date(2023, 2, 28)


def test_current_period_and_first_year():
    assert current_period(date(2026, 1, 1), date(2026, 6, 1)) is None
    period = current_period(date(2022, 1, 10), date(2026, 11, 24))
    assert (period.start, period.end) == (date(2026, 1, 10), date(2027, 1, 10))


def test_ledger_counts_only_inside_the_period():
    ledger = VacationLedger(
        {
            "EMP-1": [
                {"start": "2026-01-09", "days": 3},
                {"start": "2026-01-10", "days": 2},
            ]
        }
    )
    assert ledger.taken_between("EMP-1", date(2026, 1, 10), date(2027, 1, 10)) == 2
    assert ledger.taken_between("EMP-2", date(2026, 1, 10), date(2027, 1, 10)) == 0


def test_directory_hides_personal_data(directory):
    employee = directory.get("emp-0004")
    assert employee.name == "Jorge Díaz"
    assert set(employee.public_dict()) == {
        "id",
        "name",
        "department",
        "role",
        "start_date",
        "status",
    }
    assert directory.get("EMP-9999") is None


def test_departments_ignore_accents(directory):
    assert normalize("Tecnología") == "tecnologia"
    assert directory.resolve_department("dame el resumen de tecnologia") == "Tecnología"
    assert (
        directory.resolve_department("área de recursos humanos") == "Recursos Humanos"
    )
    assert directory.resolve_department("marketing") is None
    assert [e.id for e in directory.by_department("finanzas")] == [
        "EMP-0005",
        "EMP-0007",
    ]


def test_department_facts(directory):
    facts = department_facts(
        "Tecnología", directory.by_department("Tecnología"), date(2026, 11, 24)
    )
    assert (facts.headcount, facts.active, facts.inactive) == (3, 2, 1)
    assert facts.avg_tenure_years == 5.5
    assert facts.roles == {"Analista de datos": 1, "Líder técnico": 1}
    assert "active_names" in facts.as_dict()


def test_department_without_active_people():
    facts = department_facts("Vacío", [], date(2026, 1, 1))
    assert facts.avg_tenure_years == 0.0 and facts.headcount == 0
