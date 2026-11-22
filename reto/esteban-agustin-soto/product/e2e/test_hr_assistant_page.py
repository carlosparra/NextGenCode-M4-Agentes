"""Pruebas de punta a punta de la página del HR Assistant."""
import os
import re

import pytest
from playwright.sync_api import Page, expect


def ask(page: Page, question: str) -> None:
    """Escribe una pregunta y la envía con el botón.

    :param page: Página de Playwright
    :type page: Page
    :param question: Texto de la pregunta
    :type question: str
    :return: None
    :rtype: None
    """
    page.get_by_test_id("question").fill(question)
    page.get_by_test_id("send").click()


@pytest.fixture
def signed_page(page: Page) -> Page:
    """Abre la página y escribe la clave de E2E_API_KEY en su campo.

    :param page: Página de Playwright
    :type page: Page
    :return: La misma página, lista para preguntar
    :rtype: Page
    """
    page.goto("/")
    page.get_by_test_id("api-key").fill(os.environ["E2E_API_KEY"])
    return page


def test_user_sees_answer_after_sending_a_question(signed_page: Page) -> None:
    """La respuesta aparece en la conversación.

    :param signed_page: Página ya con la clave escrita
    :type signed_page: Page
    :return: None
    :rtype: None
    """
    ask(signed_page, "Dame los datos de EMP-0004")
    expect(signed_page.get_by_test_id("answer")).to_contain_text("Según el directorio")


def test_user_sees_the_request_id_after_an_answer(signed_page: Page) -> None:
    """El identificador de la petición se muestra tras responder.

    :param signed_page: Página ya con la clave escrita
    :type signed_page: Page
    :return: None
    :rtype: None
    """
    expect(signed_page.get_by_test_id("request-id")).to_be_empty()
    ask(signed_page, "Dame los datos de EMP-0004")
    expect(signed_page.get_by_test_id("request-id")).to_have_text(re.compile(r"\S+"))


def test_empty_question_shows_a_spanish_error_message(signed_page: Page) -> None:
    """Una pregunta vacía muestra un error en español y no llama a la API.

    :param signed_page: Página ya con la clave escrita
    :type signed_page: Page
    :return: None
    :rtype: None
    """
    signed_page.get_by_test_id("send").click()
    expect(signed_page.get_by_test_id("answer")).to_contain_text("Escribe una pregunta")
    expect(signed_page.get_by_test_id("request-id")).to_be_empty()


def test_second_question_keeps_the_previous_conversation(signed_page: Page) -> None:
    """La primera pregunta y su respuesta siguen visibles tras la segunda.

    :param signed_page: Página ya con la clave escrita
    :type signed_page: Page
    :return: None
    :rtype: None
    """
    ask(signed_page, "Dame los datos de EMP-0004")
    expect(signed_page.get_by_test_id("answer")).to_contain_text("Según el directorio")
    ask(signed_page, "Dame los datos de EMP-0001")
    answer = signed_page.get_by_test_id("answer")
    expect(answer).to_contain_text("EMP-0004")
    expect(answer).to_contain_text("EMP-0001")


def test_question_field_is_cleared_after_sending(signed_page: Page) -> None:
    """El campo queda vacío y el botón disponible tras enviar.

    :param signed_page: Página ya con la clave escrita
    :type signed_page: Page
    :return: None
    :rtype: None
    """
    ask(signed_page, "Dame los datos de EMP-0004")
    expect(signed_page.get_by_test_id("question")).to_have_value("")
    expect(signed_page.get_by_test_id("send")).to_be_enabled()


def test_wrong_api_key_shows_invalid_key_message(page: Page) -> None:
    """Una clave equivocada muestra «Clave inválida».

    :param page: Página de Playwright
    :type page: Page
    :return: None
    :rtype: None
    """
    page.goto("/")
    page.get_by_test_id("api-key").fill(os.environ["E2E_API_KEY"] + "-wrong")
    ask(page, "Dame los datos de EMP-0004")
    expect(page.get_by_test_id("answer")).to_contain_text("Clave inválida")
