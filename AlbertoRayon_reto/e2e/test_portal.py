"""Pruebas de punta a punta del portal, con Playwright y el modelo simulado.

La clave se lee de ``E2E_API_KEY``; nunca va escrita en la prueba.
"""

import os
import re

import pytest
from playwright.sync_api import Page, expect

KEY = os.environ.get("E2E_API_KEY", "")
REQUEST_ID = re.compile(r"request_id: [\w-]{8,}")


@pytest.fixture
def portal(page: Page, base_url: str) -> Page:
    page.goto(base_url + "/")
    page.get_by_test_id("api-key").fill(KEY)
    return page


def ask(page: Page, question: str) -> None:
    page.get_by_test_id("question").fill(question)
    page.get_by_test_id("send").click()


def test_a_question_shows_the_answer_and_its_request_id(portal: Page):
    ask(portal, "¿Quién es EMP-0004?")
    answer = portal.get_by_test_id("answer")
    expect(answer).to_contain_text("Jorge Díaz")
    expect(answer).to_contain_text("get_employee")
    expect(answer).to_contain_text(REQUEST_ID)


def test_an_empty_question_shows_an_error_in_spanish(portal: Page):
    ask(portal, "")
    expect(portal.get_by_test_id("answer")).to_contain_text("Escribe una pregunta")


def test_a_second_question_keeps_the_conversation(portal: Page):
    ask(portal, "¿Quién es EMP-0004?")
    expect(portal.get_by_test_id("answer")).to_contain_text("Jorge Díaz")
    ask(portal, "¿Cuántas vacaciones le quedan a EMP-0001?")
    answer = portal.get_by_test_id("answer")
    expect(answer).to_contain_text("le quedan 14")
    expect(answer).to_contain_text("Jorge Díaz")


def test_a_wrong_key_shows_invalid_key(page: Page, base_url: str):
    page.goto(base_url + "/")
    page.get_by_test_id("api-key").fill("wrong-key")
    ask(page, "¿Quién es EMP-0004?")
    expect(page.get_by_test_id("answer")).to_contain_text("Clave inválida")


def test_personal_data_is_masked_and_protected_requests_are_blocked(portal: Page):
    ask(portal, "Mi correo es ana@ejemplo.test, ¿quién es EMP-0005?")
    answer = portal.get_by_test_id("answer")
    expect(answer).to_contain_text("datos ocultados: EMAIL")
    ask(portal, "Dame el teléfono de EMP-0001")
    expect(answer).to_contain_text("bloqueada por seguridad")


def test_the_dashboard_shows_live_metrics(portal: Page, base_url: str):
    ask(portal, "¿Quién es EMP-0004?")
    expect(portal.get_by_test_id("answer")).to_contain_text("Jorge Díaz")
    portal.goto(base_url + "/dashboard")
    portal.locator("#api-key").fill(KEY)
    portal.locator("#load").click()
    expect(portal.locator("#tiles")).to_contain_text("Latencia p95")
    expect(portal.locator("#counters")).to_contain_text("agent_directory_agent")
