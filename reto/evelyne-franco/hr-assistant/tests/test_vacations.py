"""Pruebas de la herramienta ``vacation_days`` (Adenda 1, A3 y A4).

El calculo se hace en codigo con el reloj inyectado (``FakeClock``),
nunca con ``datetime.now()``: con el reloj fijo el resultado no depende
de la fecha real. Los datos son ``SAMPLE_EMPLOYEES``.
"""

from datetime import datetime, timezone

from app.llm import TOOL_RESULT_PREFIX
from tests.conftest import ADENDA_NOW, FakeClock, SpyModel
from tests.sample_data import FIRST_YEAR_NOTE, INACTIVE_NOTE, JORGE_RESULT

# Años de servicio y dias que pide la politica de vacaciones.
DAYS_BY_YEARS = {0: 0, 1: 12, 2: 14, 4: 18, 5: 20, 6: 22, 10: 22, 11: 24, 16: 26}
RESULT_KEYS = {
    "employee_id",
    "name",
    "start_date",
    "status",
    "years_of_service",
    "days",
    "note",
}


def VacationBook(directory, clock):  # pylint: disable=invalid-name
    """Construye ``app.vacations.VacationBook``.

    Importacion perezosa: el modulo es nuevo en la Adenda 1.

    :param directory: Directorio de empleados.
    :type directory: app.directory.Directory
    :param clock: Reloj inyectado.
    :type clock: tests.conftest.FakeClock
    :return: Libro de vacaciones.
    :rtype: app.vacations.VacationBook
    """
    from app import vacations  # pylint: disable=import-outside-toplevel

    return vacations.VacationBook(directory, clock)


def vacation_days_for(years):
    """Llama a ``app.vacations.vacation_days_for`` (importacion perezosa).

    :param years: Años completos de servicio.
    :type years: int
    :return: Dias habiles de vacaciones.
    :rtype: int
    """
    from app import vacations  # pylint: disable=import-outside-toplevel

    return vacations.vacation_days_for(years)


def _tool_results(spy):
    """Devuelve los resultados de herramienta que recibio el especialista.

    Solo los mensajes con ``TOOL_RESULT_PREFIX``, para no confundirlos
    con el prompt de sistema.

    :param spy: Modelo espia.
    :type spy: tests.spies.SpyModel
    :return: Contenido de cada resultado, en orden de llegada.
    :rtype: list[str]
    """
    return [
        m["content"]
        for call in spy.specialist_calls
        for m in call
        if str(m.get("content", "")).startswith(TOOL_RESULT_PREFIX)
    ]


def _audited_tools(harness):
    """Devuelve las herramientas de los eventos ``audit``.

    :param harness: Arnes de la aplicacion.
    :type harness: tests.conftest.Harness
    :return: Nombre de herramienta de cada evento.
    :rtype: list[str]
    """
    return [e.get("tool") for e in harness.events("audit")]


def _book(directory, year, month, day):
    """Arma un ``VacationBook`` con el reloj fijo en una fecha UTC.

    :param directory: Directorio de prueba.
    :type directory: app.directory.Directory
    :param year: Año del reloj.
    :type year: int
    :param month: Mes del reloj.
    :type month: int
    :param day: Dia del reloj.
    :type day: int
    :return: Libro de vacaciones.
    :rtype: app.vacations.VacationBook
    """
    now = datetime(year, month, day, 12, 0, 0, tzinfo=timezone.utc)
    return VacationBook(directory, FakeClock(now=now))


def test_vacation_days_follow_the_policy_table():
    """0, 1, 4, 5, 6, 10 y 11 años dan 0, 12, 18, 20, 22, 22 y 24 dias."""
    for years, days in DAYS_BY_YEARS.items():
        assert vacation_days_for(years) == days, years


def test_an_active_employee_gets_exactly_the_documented_fields(directory):
    """EMP-0004 en 2026-11-19: 4 años, 18 dias y nota vacia."""
    book = VacationBook(directory, FakeClock(now=ADENDA_NOW))

    result = book.vacation_days("EMP-0004")

    assert set(result) == RESULT_KEYS
    assert result == JORGE_RESULT


def test_the_anniversary_day_adds_a_year_according_to_the_injected_clock(
    directory,
):
    """Un dia antes del aniversario son 3 años; ese dia ya son 4."""
    before = _book(directory, 2026, 1, 9).vacation_days("EMP-0004")
    on_the_day = _book(directory, 2026, 1, 10).vacation_days("EMP-0004")

    assert (before["years_of_service"], before["days"]) == (3, 16)
    assert (on_the_day["years_of_service"], on_the_day["days"]) == (4, 18)


def test_an_employee_in_the_first_year_gets_no_days_and_a_note(directory):
    """Con menos de 1 año: ``days = 0`` y la nota del primer año."""
    result = _book(directory, 2022, 6, 1).vacation_days("EMP-0004")

    assert result["years_of_service"] == 0
    assert result["days"] == 0
    assert result["note"] == FIRST_YEAR_NOTE


def test_an_inactive_employee_gets_no_days_and_a_note(directory):
    """EMP-0003 esta de baja: ``days = 0`` aunque tenga 10 años."""
    result = VacationBook(directory, FakeClock(now=ADENDA_NOW)).vacation_days(
        "EMP-0003"
    )

    assert result["status"] == "baja"
    assert result["years_of_service"] == 10
    assert result["days"] == 0
    assert result["note"] == INACTIVE_NOTE


def test_an_unknown_employee_is_reported(directory):
    """Un id que no existe devuelve solo el error, sin datos."""
    book = VacationBook(directory, FakeClock(now=ADENDA_NOW))

    assert book.vacation_days("EMP-0099") == {"error": "empleado no encontrado"}


def test_an_invalid_employee_id_is_rejected_before_the_tool_runs(build_harness):
    """Un nombre en lugar de id no llama a la herramienta.

    Se registra ``security`` con ``control=tool_args``, no hay ``audit``
    de ``vacation_days`` y el modelo recibe el error de la spec.
    """
    spy = SpyModel(
        replies=[
            {"tool": "vacation_days", "args": {"employee_id": "Jorge Diaz"}},
            {"answer": "Listo."},
        ]
    )
    harness = build_harness(model=spy, now=ADENDA_NOW)

    response = harness.client.post(
        "/ask", json={"question": "¿Cuántos días de vacaciones tengo?"}
    )

    assert response.status_code == 200
    controls = [e["control"] for e in harness.events("security")]
    assert controls.count("tool_args") == 1
    assert "vacation_days" not in _audited_tools(harness)
    results = " ".join(_tool_results(spy))
    assert "empleado no encontrado" in results
    assert "years_of_service" not in results


def test_the_directory_specialist_cannot_compute_vacation_days(build_harness):
    """Minimo privilegio: ``vacation_days`` desde ``directory`` no corre."""
    spy = SpyModel(
        replies=[
            {"tool": "vacation_days", "args": {"employee_id": "EMP-0004"}},
            {"answer": "Listo."},
        ]
    )
    harness = build_harness(model=spy, now=ADENDA_NOW)

    response = harness.client.post("/ask", json={"question": "¿Quién es EMP-0004?"})

    assert response.json()["specialist"] == "directory"
    assert "years_of_service" not in " ".join(_tool_results(spy))
    assert "vacation_days" not in _audited_tools(harness)


def test_vacations_by_employee_are_looked_up_in_code_before_the_question(
    build_harness,
):
    """A4: ``search_policy`` y luego ``vacation_days``, antes de la pregunta.

    Las dos cuentan en ``tools_used`` y dejan su ``audit`` ``tool_call``.
    El especialista ve el id ya normalizado por ``guard``.
    """
    spy = SpyModel()
    harness = build_harness(model=spy, now=ADENDA_NOW)

    response = harness.client.post(
        "/ask",
        json={"question": "¿Cuántos días de vacaciones tiene el empleado 004?"},
    )

    body = response.json()
    assert body["tools_used"] == ["search_policy", "vacation_days"]
    audits = [
        (e["action"], e["tool"])
        for e in harness.events("audit")
        if e["request_id"] == body["request_id"]
    ]
    assert audits == [("tool_call", "search_policy"), ("tool_call", "vacation_days")]
    first_call = [str(m["content"]) for m in spy.specialist_calls[0]]
    results = [c for c in first_call if c.startswith(TOOL_RESULT_PREFIX)]
    assert len(results) == 2
    assert "12 días hábiles" in results[0]
    assert "years_of_service" in results[1]
    assert "Jorge Diaz" in results[1]
    # Los dos resultados van antes de la pregunta, ya normalizada.
    assert first_call.index(results[1]) < len(first_call) - 1
    assert "EMP-0004" in first_call[-1]
    assert "empleado 004" not in first_call[-1]
