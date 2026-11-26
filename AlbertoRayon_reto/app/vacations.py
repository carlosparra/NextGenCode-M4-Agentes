"""Saldo de vacaciones según la Ley Federal del Trabajo (artículo 76, reforma 2023).

El cálculo vive en código: el modelo elige la herramienta, pero no decide los números.
"""

import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from app.directory import Employee

FIRST_YEARS = {1: 12, 2: 14, 3: 16, 4: 18, 5: 20}
DAYS_AFTER_FIVE_YEARS = 22
BLOCK_YEARS = 5
DAYS_PER_BLOCK = 2


def entitlement_days(years: int) -> int:
    """Días de vacaciones que marca la ley para los años cumplidos.

    :param years: Años de servicio cumplidos
    :type years: int
    :return: 12 días el primer año, 2 más por año hasta 20, y desde el sexto año
        2 más por cada cinco años; 0 antes del primer año
    :rtype: int
    """
    if years < 1:
        return 0
    if years in FIRST_YEARS:
        return FIRST_YEARS[years]
    return DAYS_AFTER_FIVE_YEARS + DAYS_PER_BLOCK * ((years - 6) // BLOCK_YEARS)


def _anniversary(start: date, year: int) -> date:
    try:
        return start.replace(year=year)
    except ValueError:  # 29 de febrero en un año que no es bisiesto
        return start.replace(year=year, day=28)


def years_of_service(start: date, today: date) -> int:
    """Años cumplidos entre el ingreso y hoy.

    :param start: Fecha de ingreso
    :type start: datetime.date
    :param today: Fecha de consulta
    :type today: datetime.date
    :return: Años completos (0 si todavía no ingresa)
    :rtype: int
    """
    years = today.year - start.year
    if _anniversary(start, today.year) > today:
        years -= 1
    return max(years, 0)


@dataclass(frozen=True)
class VacationBalance:  # pylint: disable=too-many-instance-attributes
    """Saldo de vacaciones de un empleado en su periodo vigente."""

    employee_id: str
    name: str
    eligible: bool
    years_of_service: int
    entitled_days: int
    taken_days: int
    remaining_days: int
    period_start: str
    period_end: str
    note: str

    def as_dict(self) -> dict:
        """El saldo como diccionario.

        :return: Los campos del saldo
        :rtype: dict
        """
        return asdict(self)

    def describe(self) -> str:
        """Respuesta en español con las cifras verificadas.

        :return: Texto listo para la persona
        :rtype: str
        """
        if not self.eligible:
            return f"{self.name} ({self.employee_id}): {self.note}"
        return (
            f"{self.name} ({self.employee_id}) tiene {self.years_of_service} años de "
            f"servicio: le corresponden {self.entitled_days} días, ha tomado "
            f"{self.taken_days} y le quedan {self.remaining_days} en el periodo "
            f"{self.period_start} a {self.period_end}. {self.note}"
        )


class VacationLedger:
    """Días de vacaciones tomados, por empleado."""

    def __init__(self, taken: dict[str, list[dict]]):
        self._taken = taken

    @classmethod
    def from_file(cls, path: Path) -> "VacationLedger":
        """Carga el registro de días tomados.

        :param path: Archivo JSON ``{id: [{"start", "days"}]}``
        :type path: pathlib.Path
        :return: Registro listo para consultar
        :rtype: VacationLedger
        """
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def taken_between(self, employee_id: str, start: date, end: date) -> int:
        """Días tomados dentro de un periodo.

        :param employee_id: Id del empleado
        :type employee_id: str
        :param start: Primer día del periodo
        :type start: datetime.date
        :param end: Primer día del periodo siguiente
        :type end: datetime.date
        :return: Suma de días tomados
        :rtype: int
        """
        return sum(
            record["days"]
            for record in self._taken.get(employee_id, [])
            if start <= date.fromisoformat(record["start"]) < end
        )

    def balance(self, employee: Employee, today: date) -> VacationBalance:
        """Calcula el saldo del periodo vigente.

        :param employee: Empleado a consultar
        :type employee: Employee
        :param today: Fecha de consulta
        :type today: datetime.date
        :return: Saldo con días que corresponden, tomados y restantes
        :rtype: VacationBalance
        """
        years = years_of_service(employee.start_date, today)
        start = _anniversary(employee.start_date, employee.start_date.year + years)
        end = _anniversary(employee.start_date, start.year + 1)
        if not employee.active or years < 1:
            note = (
                "No tiene saldo de vacaciones porque está dado de baja."
                if not employee.active
                else "Todavía no cumple un año de servicio, así que no genera días."
            )
            return VacationBalance(
                employee.id, employee.name, False, years, 0, 0, 0,
                start.isoformat(), end.isoformat(), note,
            )
        entitled = entitlement_days(years)
        taken = self.taken_between(employee.id, start, end)
        return VacationBalance(
            employee.id, employee.name, True, years, entitled, taken,
            max(entitled - taken, 0), start.isoformat(), end.isoformat(),
            "Cálculo según el artículo 76 de la LFT.",
        )
