"""Cálculo de vacaciones según la Ley Federal del Trabajo (reforma 2023).

Es lógica pura y determinista: el modelo de lenguaje nunca calcula días; solo
explica los números que calcula este módulo.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

# Artículo 76 LFT: 12 días el primer año, +2 por año hasta el quinto (20),
# y +2 por cada quinquenio a partir del sexto año.
_FIRST_YEARS = {1: 12, 2: 14, 3: 16, 4: 18, 5: 20}


def entitled_days(years_of_service: int) -> int:
    """Días de vacaciones que corresponden por años cumplidos.

    :param years_of_service: Años completos de servicio
    :type years_of_service: int
    :return: Días de vacaciones; 0 si aún no cumple un año
    :rtype: int
    """
    if years_of_service < 1:
        return 0
    if years_of_service in _FIRST_YEARS:
        return _FIRST_YEARS[years_of_service]
    return 22 + 2 * ((years_of_service - 6) // 5)


def years_between(start: date, end: date) -> int:
    """Años completos entre dos fechas.

    :param start: Fecha de ingreso
    :type start: date
    :param end: Fecha de corte
    :type end: date
    :return: Años cumplidos (0 si ``end`` es anterior)
    :rtype: int
    """
    years = end.year - start.year - ((end.month, end.day) < (start.month, start.day))
    return max(years, 0)


def anniversary(start: date, year: int) -> date:
    """Aniversario de ingreso en un año dado (29 de febrero pasa al 28).

    :param start: Fecha de ingreso
    :type start: date
    :param year: Año del aniversario
    :type year: int
    :return: Fecha del aniversario
    :rtype: date
    """
    try:
        return start.replace(year=year)
    except ValueError:
        return start.replace(year=year, day=28)


@dataclass(frozen=True)
class VacationPeriod:
    """Periodo vacacional vigente: del último aniversario al siguiente."""

    start: date
    end: date


def current_period(start_date: date, as_of: date) -> VacationPeriod | None:
    """Periodo vacacional vigente a una fecha.

    :param start_date: Fecha de ingreso
    :type start_date: date
    :param as_of: Fecha de corte
    :type as_of: date
    :return: Periodo, o ``None`` si aún no cumple un año
    :rtype: VacationPeriod | None
    """
    years = years_between(start_date, as_of)
    if years < 1:
        return None
    begin = anniversary(start_date, start_date.year + years)
    return VacationPeriod(begin, anniversary(start_date, start_date.year + years + 1))


class VacationLedger:
    """Registro de días de vacaciones tomados por empleado.

    :param records: ``{"EMP-0001": [{"start": "2026-04-06", "days": 5}]}``
    :type records: dict
    """

    def __init__(self, records: dict[str, list[dict]]) -> None:
        self._records = {
            key: [(date.fromisoformat(r["start"]), int(r["days"])) for r in value]
            for key, value in records.items()
        }

    @classmethod
    def from_file(cls, path: Path) -> "VacationLedger":
        """Carga el registro desde JSON.

        :param path: Ruta al archivo
        :type path: pathlib.Path
        :return: Registro cargado
        :rtype: VacationLedger
        """
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def taken_between(self, employee_id: str, start: date, end: date) -> int:
        """Días tomados dentro de un periodo ``[start, end)``.

        :param employee_id: Id del empleado
        :type employee_id: str
        :param start: Inicio del periodo
        :type start: date
        :param end: Fin del periodo (exclusivo)
        :type end: date
        :return: Total de días
        :rtype: int
        """
        return sum(
            days
            for when, days in self._records.get(employee_id, [])
            if start <= when < end
        )
