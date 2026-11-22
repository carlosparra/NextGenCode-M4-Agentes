"""Pruebas de punta a punta de la conversación en el navegador.

Corren contra el producto levantado con el modelo simulado; la URL base la pone
la verificación. La clave del cliente se lee de la variable ``E2E_API_KEY``,
que también pone la verificación: nunca se escribe en la prueba.
"""

import json
import os
import re
from pathlib import Path

from playwright.sync_api import Page, expect

FIRST_QUESTION = "¿Quién es EMP-0001?"
SECOND_QUESTION = "¿En qué departamento trabaja EMP-0002?"
VACATION_EMPLOYEE_ID = "EMP-0004"
VACATION_QUESTION = f"¿Cuántos días de vacaciones le quedan a {VACATION_EMPLOYEE_ID}?"
PERSONAL_EMAIL = "ana@example.com"
PII_QUESTION = f"mi correo es {PERSONAL_EMAIL}, ¿quién es EMP-0001?"
EMPTY_QUESTION_ERROR = "Escribe una pregunta antes de enviar."
INVALID_KEY_ERROR = "Clave inválida"
REQUEST_ID_PATTERN = re.compile(r"Id de la petición: \S+")
# Cualquier texto con al menos un carácter visible.
NON_EMPTY_TEXT_PATTERN = re.compile(r"\S")
# Datos que sirve el producto; de aquí se calcula el saldo esperado.
EMPLOYEES_PATH = Path(__file__).resolve().parents[1] / "data" / "employees.json"


def _valid_api_key() -> str:
    """Devuelve la clave válida que pone la verificación.

    :return: Clave del cliente de pruebas
    :rtype: str
    """
    return os.environ["E2E_API_KEY"]


def _available_vacation_days(employee_id: str) -> int:
    """Calcula los días de vacaciones disponibles de un empleado en los datos.

    :param employee_id: Id del empleado, por ejemplo ``EMP-0004``
    :type employee_id: str
    :return: Días totales menos días tomados
    :rtype: int
    :raises LookupError: Si el empleado no está en los datos
    """
    employees = json.loads(EMPLOYEES_PATH.read_text(encoding="utf-8"))
    for employee in employees:
        if employee.get("id") == employee_id:
            return employee["vacation_days_total"] - employee["vacation_days_taken"]
    raise LookupError(f"Employee not found in data: {employee_id}")


def _open_with_key(page: Page, api_key: str) -> None:
    """Abre la página y escribe la clave en su campo.

    :param page: Página de Playwright
    :type page: Page
    :param api_key: Clave que se escribe en el campo
    :type api_key: str
    """
    page.goto("/")
    page.get_by_test_id("api-key").fill(api_key)


def _ask(page: Page, question: str) -> None:
    """Escribe una pregunta en la caja de texto y la envía.

    :param page: Página de Playwright con el producto abierto
    :type page: Page
    :param question: Texto de la pregunta
    :type question: str
    """
    page.get_by_test_id("question").fill(question)
    page.get_by_test_id("send").click()


def test_sending_a_question_shows_the_answer_and_its_request_id(page: Page):
    """Al enviar una pregunta se ven la pregunta, la respuesta y su request_id."""
    _open_with_key(page, _valid_api_key())
    _ask(page, FIRST_QUESTION)

    answer = page.get_by_test_id("answer")
    expect(answer).to_contain_text(FIRST_QUESTION)
    assistant_answers = page.get_by_test_id("assistant-answer")
    expect(assistant_answers).to_have_count(1)
    expect(assistant_answers.first).to_have_text(NON_EMPTY_TEXT_PATTERN)
    request_ids = page.get_by_test_id("request-id")
    expect(request_ids).to_have_count(1)
    expect(request_ids.first).to_have_text(REQUEST_ID_PATTERN)
    expect(page.get_by_test_id("send")).to_be_enabled()
    expect(page.get_by_test_id("question")).to_have_value("")


def test_an_empty_question_shows_an_error_in_spanish(page: Page):
    """Una pregunta vacía muestra un error en español y no llega a la API."""
    _open_with_key(page, _valid_api_key())
    _ask(page, "   ")

    expect(page.get_by_test_id("answer")).to_contain_text(EMPTY_QUESTION_ERROR)
    expect(page.get_by_test_id("request-id")).to_have_count(0)


def test_a_second_question_keeps_the_previous_conversation_on_screen(page: Page):
    """Tras una segunda pregunta sigue visible la primera con su respuesta."""
    _open_with_key(page, _valid_api_key())
    _ask(page, FIRST_QUESTION)
    expect(page.get_by_test_id("request-id")).to_have_count(1)

    _ask(page, SECOND_QUESTION)

    answer = page.get_by_test_id("answer")
    request_ids = page.get_by_test_id("request-id")
    expect(request_ids).to_have_count(2)
    expect(answer).to_contain_text(FIRST_QUESTION)
    expect(answer).to_contain_text(SECOND_QUESTION)
    expect(request_ids.nth(0)).to_have_text(REQUEST_ID_PATTERN)
    expect(request_ids.nth(1)).to_have_text(REQUEST_ID_PATTERN)
    assistant_answers = page.get_by_test_id("assistant-answer")
    expect(assistant_answers).to_have_count(2)
    expect(assistant_answers.nth(0)).to_have_text(NON_EMPTY_TEXT_PATTERN)
    expect(assistant_answers.nth(1)).to_have_text(NON_EMPTY_TEXT_PATTERN)


def test_a_wrong_api_key_is_hidden_and_shows_invalid_key(page: Page):
    """El campo de la clave la oculta; una clave equivocada da «Clave inválida»."""
    page.goto("/")
    expect(page.get_by_test_id("api-key")).to_have_attribute("type", "password")

    # Se deriva de la clave válida para que nunca coincida con ella.
    _open_with_key(page, _valid_api_key() + "-wrong")
    _ask(page, FIRST_QUESTION)

    expect(page.get_by_test_id("answer")).to_contain_text(INVALID_KEY_ERROR)
    expect(page.get_by_test_id("assistant-answer")).to_have_count(0)


def test_asking_for_a_vacation_balance_shows_the_available_days(page: Page):
    """El saldo de EMP-0004 muestra su número de días disponibles."""
    available_days = _available_vacation_days(VACATION_EMPLOYEE_ID)
    _open_with_key(page, _valid_api_key())
    _ask(page, VACATION_QUESTION)

    assistant_answers = page.get_by_test_id("assistant-answer")
    expect(assistant_answers).to_have_count(1)
    # El número va aislado: no cuenta si solo aparece dentro de otro número.
    expect(assistant_answers.first).to_have_text(
        re.compile(rf"(?<!\d){available_days}(?!\d)")
    )
    expect(page.get_by_test_id("request-id")).to_have_count(1)


def test_a_question_with_an_email_is_answered_without_showing_the_email(
    page: Page,
):
    """Una pregunta con un correo se responde y la página nunca muestra el correo."""
    _open_with_key(page, _valid_api_key())
    _ask(page, PII_QUESTION)

    assistant_answers = page.get_by_test_id("assistant-answer")
    expect(assistant_answers).to_have_count(1)
    expect(assistant_answers.first).to_have_text(NON_EMPTY_TEXT_PATTERN)
    request_ids = page.get_by_test_id("request-id")
    expect(request_ids).to_have_count(1)
    expect(request_ids.first).to_have_text(REQUEST_ID_PATTERN)
    # Se revisa ya con la respuesta pintada, para no pasar por llegar antes.
    expect(page.get_by_test_id("answer")).not_to_contain_text(PERSONAL_EMAIL)
    expect(page.get_by_test_id("question")).to_have_value("")
