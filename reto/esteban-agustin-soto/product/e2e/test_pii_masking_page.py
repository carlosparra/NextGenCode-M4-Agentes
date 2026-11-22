"""Prueba de punta a punta del enmascarado de PII (CURP y correo) en la página."""
import os

import pytest
from playwright.sync_api import Page, expect

FAKE_CURP = "AAAA010101HDFBBB09"
FAKE_EMAIL = "persona.prueba@example.com"


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


def send_question(page: Page, question: str) -> None:
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


def test_assistant_answer_never_shows_the_curp_or_the_email(signed_page: Page) -> None:
    """La respuesta del asistente no repite la CURP ni el correo escritos.

    La página no tiene un data-testid solo para la respuesta del asistente:
    ``answer`` contiene toda la conversación, incluido lo que escribió la
    persona. Por eso se acota al elemento de la respuesta con la clase
    ``assistant`` que la propia página le pone, dentro de ``answer``.

    :param signed_page: Página ya con la clave escrita
    :type signed_page: Page
    :return: None
    :rtype: None
    """
    conversation = signed_page.get_by_test_id("answer")
    reply = conversation.locator(".assistant")

    send_question(
        signed_page,
        f"Mi CURP es {FAKE_CURP} y mi correo es {FAKE_EMAIL}, dame los datos de EMP-0004",
    )

    expect(reply).to_have_count(1)
    expect(reply).to_be_visible()
    expect(reply).not_to_contain_text(FAKE_CURP)
    expect(reply).not_to_contain_text(FAKE_EMAIL)

    # La página sigue mostrando lo que la persona escribió: la prueba no lo evalúa.
    expect(conversation).to_contain_text(FAKE_CURP)

    # Una pregunta con un empleado válido sigue funcionando.
    send_question(signed_page, "Dame los datos de EMP-0004")
    expect(reply).to_have_count(2)
    expect(reply.last).to_contain_text("EMP-0004")
