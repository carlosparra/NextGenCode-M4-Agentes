"""Pruebas de la normalizacion de ids de empleado (Adenda 1, A1).

``normalize_employee_ids`` convierte «empleado 4», «empleado 004»,
«empleado #4», «emp 4», «emp-4» y «EMP4» (de 1 a 4 digitos, sin
importar mayusculas) en ``EMP-0004``. Un numero sin la palabra
«empleado» o «emp» no es un id.
"""

from app.guard import screen_input
from app.security import NullAudit


def normalize_employee_ids(text):
    """Llama a ``app.employee_ids.normalize_employee_ids``.

    Importacion perezosa: el modulo es nuevo en la Adenda 1 y asi el
    resto de las pruebas se recolecta aunque todavia no exista.

    :param text: Texto ya limpio de PII.
    :type text: str
    :return: Texto con los ids en forma ``EMP-dddd``.
    :rtype: str
    """
    from app import employee_ids  # pylint: disable=import-outside-toplevel

    return employee_ids.normalize_employee_ids(text)

WRITTEN_FORMS = (
    "empleado 4",
    "empleado 004",
    "empleado #4",
    "emp 4",
    "emp-4",
    "EMP4",
    "Empleado 4",
    "EMPLEADO #004",
    "Emp-4",
)
NOT_IDS = (
    "Entré en 2021.",
    "Desde el año 2021.",
    "Somos 4 empleados 4 veces.",
    "La empresa 4 es otra.",
    "El emp 12345 no es un id.",
)


def test_every_written_form_becomes_the_canonical_id():
    """Cada forma de A1, en mayusculas o minusculas, da ``EMP-0004``."""
    for form in WRITTEN_FORMS:
        normalized = normalize_employee_ids(f"¿Quién es el {form}?")
        assert normalized == "¿Quién es el EMP-0004?", form


def test_leading_zeros_give_the_same_id():
    """``4``, ``04``, ``004`` y ``0004`` son el mismo empleado."""
    for digits in ("4", "04", "004", "0004"):
        assert normalize_employee_ids(f"empleado {digits}") == "EMP-0004", digits
    assert normalize_employee_ids("emp 1234") == "EMP-1234"


def test_a_canonical_id_is_left_unchanged():
    """La normalizacion es idempotente con ``EMP-dddd``."""
    text = "¿Cuántos días de vacaciones tiene EMP-0004?"

    once = normalize_employee_ids(text)

    assert once == text
    assert normalize_employee_ids(once) == text


def test_numbers_without_the_employee_word_are_not_ids():
    """«2021», «año 2021», «empleados 4», «empresa 4» y 5 digitos no cambian."""
    for text in NOT_IDS:
        assert normalize_employee_ids(text) == text, text


def test_guard_normalizes_the_clean_question_and_reports_only_a_count():
    """``guard`` oculta la PII, normaliza la pregunta y no el historial.

    El resumen para la traza lleva el conteo, nunca el texto.
    """
    history = [{"role": "user", "content": "Hablo del empleado 4"}]
    question = "Escribe a ana@empresa.com sobre el empleado 004"

    result = screen_input(question, history, NullAudit(), ("req-1", "tester"))

    assert result.question.endswith("sobre el EMP-0004")
    assert "ana@empresa.com" not in result.question
    assert result.history[0]["content"] == "Hablo del empleado 4"
    summary = result.summary()
    assert summary == {"pii_kinds": ["email"], "injection": False, "ids_normalized": 1}
    assert "EMP-0004" not in str(summary)
