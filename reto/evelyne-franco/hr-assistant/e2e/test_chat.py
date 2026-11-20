"""Pruebas de punta a punta de la página del HR Assistant (spec/04-production.md).

El producto corre con el modelo simulado; la URL base la pone la verificación.
La clave válida se lee de la variable E2E_API_KEY y nunca se escribe aquí.
"""

import os
import re

from playwright.sync_api import Page, expect

FIRST_QUESTION = "Cuantos dias de vacaciones tengo"
SECOND_QUESTION = "Y cuantos dias de permiso por enfermedad"
NON_EMPTY = re.compile(r"\S")
WAITING_TEXT = "Pensando..."
INVALID_KEY_MESSAGE = "Clave inválida"
WRONG_KEY_SUFFIX = "-wrong"


def _open_with_key(page: Page, api_key: str) -> None:
    """Abre la página y escribe la clave en su campo.

    :param page: Página de Playwright
    :type page: Page
    :param api_key: Clave que se escribe en el campo
    :type api_key: str
    """
    page.goto("/")
    page.get_by_test_id("api-key").fill(api_key)


def _open_with_valid_key(page: Page) -> None:
    """Abre la página y escribe la clave válida que pone la verificación.

    :param page: Página de Playwright
    :type page: Page
    """
    _open_with_key(page, os.environ["E2E_API_KEY"])


def _ask(page: Page, question: str) -> None:
    """Escribe una pregunta y la envía con el botón.

    :param page: Página de Playwright
    :type page: Page
    :param question: Texto de la pregunta
    :type question: str
    """
    page.get_by_test_id("question").fill(question)
    page.get_by_test_id("send").click()


def _wait_for_answer(page: Page) -> None:
    """Espera a que llegue la respuesta y su request_id.

    :param page: Página de Playwright
    :type page: Page
    """
    expect(page.get_by_test_id("request-id")).to_have_text(NON_EMPTY)
    expect(page.get_by_test_id("answer")).not_to_have_text(WAITING_TEXT)


def test_asking_a_question_shows_the_answer_and_its_request_id(page: Page):
    """Una pregunta enviada con clave muestra la respuesta y su request_id."""
    _open_with_valid_key(page)
    _ask(page, FIRST_QUESTION)

    _wait_for_answer(page)
    expect(page.get_by_test_id("answer")).to_have_text(NON_EMPTY)
    expect(page.get_by_test_id("answer")).not_to_contain_text(INVALID_KEY_MESSAGE)
    expect(page.get_by_test_id("request-id")).to_have_text(
        re.compile(r"[0-9a-fA-F-]{8,}")
    )


def test_an_empty_question_shows_an_error_message_in_spanish(page: Page):
    """Enviar una pregunta vacía muestra un mensaje de error en español."""
    _open_with_valid_key(page)
    _ask(page, "")

    expect(page.get_by_test_id("answer")).to_have_text(
        re.compile(r"\b(error|vac[ií]a|escribe|pregunta)\b", re.IGNORECASE)
    )


def test_a_second_question_keeps_the_previous_conversation_on_screen(page: Page):
    """Tras la segunda pregunta, la primera sigue visible en pantalla."""
    _open_with_valid_key(page)
    _ask(page, FIRST_QUESTION)
    _wait_for_answer(page)
    first_answer = page.get_by_test_id("answer").inner_text().strip()

    _ask(page, SECOND_QUESTION)
    expect(page.locator("body")).to_contain_text(SECOND_QUESTION)
    _wait_for_answer(page)

    expect(page.locator("body")).to_contain_text(FIRST_QUESTION)
    expect(page.locator("body")).to_contain_text(first_answer)


def test_the_api_key_field_hides_what_is_typed(page: Page):
    """El campo de clave es de tipo contraseña."""
    page.goto("/")

    expect(page.get_by_test_id("api-key")).to_have_attribute("type", "password")


def test_a_wrong_api_key_shows_invalid_key_message(page: Page):
    """Una clave equivocada muestra «Clave inválida»."""
    _open_with_key(page, os.environ["E2E_API_KEY"] + WRONG_KEY_SUFFIX)
    _ask(page, FIRST_QUESTION)

    expect(page.get_by_test_id("answer")).to_contain_text(INVALID_KEY_MESSAGE)
