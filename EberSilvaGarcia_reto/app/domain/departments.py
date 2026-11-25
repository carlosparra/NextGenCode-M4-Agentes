"""Hechos de un departamento, calculados por código.

El agente de resumen recibe estos hechos y los redacta; el crítico los usa
para comprobar que el borrador no inventa ni omite números.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date

from app.domain.directory import Employee
from app.domain.vacations import years_between


@dataclass(frozen=True)
class DepartmentFacts:
    """Lo que se sabe con certeza de un departamento."""

    department: str
    headcount: int
    active: int
    inactive: int
    avg_tenure_years: float
    roles: dict[str, int] = field(default_factory=dict)
    active_names: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        """Diccionario serializable.

        :return: Hechos del departamento
        :rtype: dict
        """
        return {
            "department": self.department,
            "headcount": self.headcount,
            "active": self.active,
            "inactive": self.inactive,
            "avg_tenure_years": self.avg_tenure_years,
            "roles": dict(self.roles),
            "active_names": list(self.active_names),
        }


def department_facts(
    department: str, employees: list[Employee], as_of: date
) -> DepartmentFacts:
    """Calcula los hechos de un departamento.

    La antigüedad promedio considera solo a los empleados activos.

    :param department: Nombre oficial del departamento
    :type department: str
    :param employees: Empleados del departamento
    :type employees: list[Employee]
    :param as_of: Fecha de corte
    :type as_of: date
    :return: Hechos calculados
    :rtype: DepartmentFacts
    """
    active = [e for e in employees if e.is_active]
    tenure = (
        round(sum(years_between(e.start_date, as_of) for e in active) / len(active), 1)
        if active
        else 0.0
    )
    return DepartmentFacts(
        department=department,
        headcount=len(employees),
        active=len(active),
        inactive=len(employees) - len(active),
        avg_tenure_years=tenure,
        roles=dict(sorted(Counter(e.role for e in active).items())),
        active_names=tuple(e.name for e in active),
    )
