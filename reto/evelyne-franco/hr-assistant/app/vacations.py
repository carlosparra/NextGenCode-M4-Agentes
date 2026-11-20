"""Dias de vacaciones por empleado, calculados en codigo (Adenda 1, A3).

La herramienta ``vacation_days`` es solo del especialista ``policy`` y
de solo lectura. Usa el reloj inyectado (``app.clock``), nunca el reloj
del sistema directamente; «hoy» es la fecha UTC de ``clock.now()``.

Tabla de la politica de vacaciones: 1 año -> 12 dias; 2 -> 14; 3 -> 16;
4 -> 18; 5 -> 20; de 6 a 10 -> 22; de 11 a 15 -> 24; y asi, 2 dias mas
por cada 5 años.

:seealso: ``spec/06-multiagente.md``, Adenda 1, A3 y A5.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from app.clock import Clock
from app.directory import Directory

EMPLOYEE_NOT_FOUND = "empleado no encontrado"
FIRST_YEAR_NOTE = (
    "Aún no cumple su primer año; al cumplirlo le corresponden 12 días hábiles."
)
INACTIVE_NOTE = "El empleado no está activo."
ACTIVE_STATUS = "activo"
FIRST_TIER_YEARS = 5
FIRST_TIER_BASE = 10
DAYS_PER_STEP = 2
SECOND_TIER_BASE = 20


def years_of_service(start: date, today: date) -> int:
    """Años completos desde ``start`` hasta ``today``.

    :param start: Fecha de ingreso.
    :type start: datetime.date
    :param today: Fecha de hoy.
    :type today: datetime.date
    :return: Años completos; nunca negativo.
    :rtype: int
    """
    years = today.year - start.year
    if (today.month, today.day) < (start.month, start.day):
        years -= 1
    return max(years, 0)


def vacation_days_for(years: int) -> int:
    """Dias habiles que corresponden segun los años de servicio.

    :param years: Años completos de servicio.
    :type years: int
    :return: Dias habiles; 0 con menos de 1 año.
    :rtype: int
    """
    if years < 1:
        return 0
    if years <= FIRST_TIER_YEARS:
        return FIRST_TIER_BASE + DAYS_PER_STEP * years
    return SECOND_TIER_BASE + DAYS_PER_STEP * ((years - 1) // FIRST_TIER_YEARS)


def vacation_sentence(result: Mapping[str, Any]) -> str:
    """Frase armada en codigo con un resultado de ``vacation_days`` (A5).

    La frase es literal, seguida de ``note`` si no esta vacia.

    :param result: Resultado de ``vacation_days`` con ``days``.
    :type result: collections.abc.Mapping[str, Any]
    :return: Respuesta lista para la persona.
    :rtype: str
    """
    sentence = (
        f"{result.get('name')} ({result.get('employee_id')}) tiene "
        f"{result.get('years_of_service')} años de servicio y le corresponden "
        f"{result.get('days')} días hábiles de vacaciones."
    )
    note = str(result.get("note") or "")
    return f"{sentence} {note}" if note else sentence


def is_vacation_result(result: Any) -> bool:
    """Indica si un valor es un resultado valido de ``vacation_days``.

    :param result: Valor devuelto por la herramienta.
    :type result: Any
    :return: ``True`` si trae ``days`` y ``years_of_service``.
    :rtype: bool
    """
    return (
        isinstance(result, dict)
        and "days" in result
        and "years_of_service" in result
    )


class VacationBook:
    """Calcula los dias de vacaciones con el directorio y el reloj.

    :param directory: Directorio de empleados.
    :type directory: app.directory.Directory
    :param clock: Reloj inyectado.
    :type clock: app.clock.Clock
    """

    def __init__(self, directory: Directory, clock: Clock) -> None:
        """Guarda el directorio y el reloj.

        :param directory: Directorio de empleados.
        :type directory: app.directory.Directory
        :param clock: Reloj inyectado.
        :type clock: app.clock.Clock
        """
        self._directory = directory
        self._clock = clock

    def vacation_days(self, employee_id: str) -> dict[str, Any]:
        """Herramienta ``vacation_days`` del especialista ``policy``.

        :param employee_id: Id ``EMP-dddd`` (ya validado).
        :type employee_id: str
        :return: ``employee_id``, ``name``, ``start_date``, ``status``,
            ``years_of_service``, ``days`` y ``note``; o
            ``{"error": "empleado no encontrado"}``.
        :rtype: dict[str, Any]
        """
        employee = self._directory.find(employee_id)
        if employee is None:
            return {"error": EMPLOYEE_NOT_FOUND}
        try:
            start = date.fromisoformat(str(employee.get("start_date", "")))
        except ValueError:
            return {"error": EMPLOYEE_NOT_FOUND}
        today = self._clock.now().date()
        years = years_of_service(start, today)
        status = str(employee.get("status", ""))
        if status != ACTIVE_STATUS:
            days, note = 0, INACTIVE_NOTE
        elif years < 1:
            days, note = 0, FIRST_YEAR_NOTE
        else:
            days, note = vacation_days_for(years), ""
        return {
            "employee_id": str(employee.get("id")),
            "name": str(employee.get("name", "")),
            "start_date": start.isoformat(),
            "status": status,
            "years_of_service": years,
            "days": days,
            "note": note,
        }
