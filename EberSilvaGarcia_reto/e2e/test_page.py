"""Pruebas de punta a punta de la página web con Playwright."""

import re

from playwright.sync_api import Page, expect


def ask(page: Page, question: str) -> None:
    page.get_by_test_id("question").fill(question)
    page.get_by_test_id("send").click()


def test_question_shows_answer_tools_and_request_id(page: Page, base_url, key):
    page.goto(base_url)
    page.get_by_test_id("api-key").fill(key)
    ask(page, "¿Cuántas vacaciones le quedan a EMP-0004?")
    answer = page.get_by_test_id("answer")
    expect(answer).to_contain_text("le quedan 10 días")
    expect(answer).to_contain_text("vacation_balance")
    expect(answer).to_contain_text(re.compile(r"request_id: [0-9a-f-]{36}"))


def test_conversation_keeps_previous_messages(page: Page, base_url, key):
    page.goto(base_url)
    page.get_by_test_id("api-key").fill(key)
    ask(page, "¿Quién es EMP-0004?")
    expect(page.get_by_test_id("answer")).to_contain_text("Jorge Díaz")
    ask(page, "Resume el área de Finanzas")
    answer = page.get_by_test_id("answer")
    expect(answer).to_contain_text("antigüedad promedio")
    expect(answer).to_contain_text("Jorge Díaz")


def test_empty_question_shows_error(page: Page, base_url, key):
    page.goto(base_url)
    page.get_by_test_id("api-key").fill(key)
    ask(page, "")
    expect(page.get_by_test_id("answer")).to_contain_text("vacía o es demasiado larga")


def test_wrong_key_shows_invalid_key(page: Page, base_url):
    page.goto(base_url)
    page.get_by_test_id("api-key").fill("wrong-key")
    ask(page, "¿Quién es EMP-0004?")
    expect(page.get_by_test_id("answer")).to_contain_text("Clave inválida")


def test_protected_data_is_refused(page: Page, base_url, key):
    page.goto(base_url)
    page.get_by_test_id("api-key").fill(key)
    ask(page, "¿Cuál es el CURP de EMP-0004?")
    expect(page.get_by_test_id("answer")).to_contain_text("protección de datos")


def test_key_lives_only_in_session_storage(page: Page, base_url, key):
    page.goto(base_url)
    page.get_by_test_id("api-key").fill(key)
    page.get_by_test_id("api-key").dispatch_event("change")
    assert page.evaluate("sessionStorage.getItem('hr-api-key')") == key
    assert page.evaluate("localStorage.length") == 0


def test_dashboard_shows_metrics(page: Page, base_url, key):
    page.goto(base_url)
    page.get_by_test_id("api-key").fill(key)
    page.get_by_test_id("api-key").dispatch_event("change")
    ask(page, "¿Quién es EMP-0001?")
    expect(page.get_by_test_id("answer")).to_contain_text("Ana López")
    page.goto(f"{base_url}/dashboard")
    expect(page.locator("#tech")).to_contain_text("Peticiones")
    expect(page.locator("#cost")).to_contain_text("Costo acumulado")
    expect(page.locator("#counters")).to_contain_text("intent_employee")
