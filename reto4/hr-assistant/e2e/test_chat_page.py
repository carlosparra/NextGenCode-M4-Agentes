"""Pruebas de punta a punta de la página del HR Assistant (spec/04-production.md).

El producto corre con el modelo simulado; la URL base y la clave ``E2E_API_KEY``
las pone la verificación. La clave nunca se escribe en estas pruebas.
"""

import os
import re

from playwright.sync_api import Page, Response, expect

FIRST_QUESTION = "¿Quién es EMP-0004?"
FIRST_EMPLOYEE_NAME = "Jorge Díaz"
SECOND_QUESTION = "¿Quién trabaja en Tecnología?"
SPANISH_ERROR = re.compile(r"no es válida|error|no se pudo", re.IGNORECASE)
INVALID_KEY_MESSAGE = "Clave inválida"
WRONG_KEY_SUFFIX = "-not-a-valid-key"


def _api_key() -> str:
    """Devuelve la clave de las pruebas desde la variable ``E2E_API_KEY``.

    :return: Clave válida que puso la verificación
    :rtype: str
    """
    return os.environ["E2E_API_KEY"]


def _open_page(page: Page, api_key: str) -> None:
    """Abre la página y escribe la clave en el campo ``api-key``.

    :param page: Página de Playwright
    :type page: playwright.sync_api.Page
    :param api_key: Clave que se escribe en el campo
    :type api_key: str
    """
    page.goto("/")
    page.get_by_test_id("api-key").fill(api_key)


def _ask(page: Page, question: str) -> Response:
    """Escribe una pregunta, la envía y devuelve la respuesta HTTP de ``/ask``.

    :param page: Página de Playwright ya abierta en ``/``
    :type page: playwright.sync_api.Page
    :param question: Texto de la pregunta
    :type question: str
    :return: Respuesta de ``POST /ask``
    :rtype: playwright.sync_api.Response
    """
    page.get_by_test_id("question").fill(question)
    with page.expect_response("**/ask") as response_info:
        page.get_by_test_id("send").click()
    return response_info.value


def test_a_question_shows_its_answer_and_request_id(page: Page):
    """Una pregunta con clave válida muestra la respuesta y su ``request_id``."""
    _open_page(page, _api_key())
    response = _ask(page, FIRST_QUESTION)
    assert response.status == 200
    request_id = response.headers.get("x-request-id", "")
    answer = page.get_by_test_id("answer")
    expect(answer).to_contain_text(FIRST_EMPLOYEE_NAME)
    assert request_id, "POST /ask no devolvió el encabezado X-Request-ID"
    expect(answer).to_contain_text(request_id)


def test_an_empty_question_shows_an_error_in_spanish(page: Page):
    """Una pregunta vacía con clave válida muestra un error en español."""
    _open_page(page, _api_key())
    response = _ask(page, "")
    assert response.status == 422
    answer = page.get_by_test_id("answer")
    expect(answer).to_contain_text(SPANISH_ERROR)
    expect(answer).not_to_contain_text("must not be empty")


def test_a_second_question_keeps_the_previous_conversation(page: Page):
    """La segunda pregunta deja en pantalla la conversación anterior."""
    _open_page(page, _api_key())
    _ask(page, FIRST_QUESTION)
    answer = page.get_by_test_id("answer")
    expect(answer).to_contain_text(FIRST_EMPLOYEE_NAME)
    second_response = _ask(page, SECOND_QUESTION)
    second_request_id = second_response.headers.get("x-request-id", "")
    assert second_request_id, "POST /ask no devolvió el encabezado X-Request-ID"
    expect(answer).to_contain_text(SECOND_QUESTION)
    expect(answer).to_contain_text(second_request_id)
    expect(answer).to_contain_text(FIRST_QUESTION)
    expect(answer).to_contain_text(FIRST_EMPLOYEE_NAME)


def test_a_wrong_api_key_shows_invalid_key(page: Page):
    """Una clave equivocada recibe ``401`` y la página muestra «Clave inválida»."""
    _open_page(page, _api_key() + WRONG_KEY_SUFFIX)
    response = _ask(page, FIRST_QUESTION)
    assert response.status == 401
    answer = page.get_by_test_id("answer")
    expect(answer).to_contain_text(INVALID_KEY_MESSAGE)
    expect(answer).not_to_contain_text(FIRST_EMPLOYEE_NAME)
