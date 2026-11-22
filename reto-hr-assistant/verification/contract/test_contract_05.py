"""Contrato del reto: herramientas nuevas y protección de datos personales."""

import json

from verification.contract.test_contract_04 import start

VACATION = {"question": "¿Cuántos días de vacaciones le quedan a EMP-0004?"}
SUMMARY = {"question": "Dame el resumen del departamento de Ventas"}
WITH_EMAIL = {"question": "Mi correo es ana@example.com, ¿quién es EMP-0001?"}
PERSONAL = ("personal@example.com", "+52 55 1234")


def test_vacation_balance_is_computed_in_code(api):
    body = api.post("/ask", json=VACATION).json()
    assert "12" in body["answer"]
    assert "get_vacation_balance" in body["tools_used"]


def test_department_summary_uses_its_tool(api):
    body = api.post("/ask", json=SUMMARY).json()
    assert "department_summary" in body["tools_used"]


def test_personal_data_never_leaves_a_tool(api):
    for question in (VACATION, SUMMARY, {"question": "¿Quién es EMP-0001?"}):
        answer = api.post("/ask", json=question).json()["answer"]
        assert not any(value in answer for value in PERSONAL)


def test_pii_in_the_question_is_redacted_and_reported(api):
    response = api.post("/ask", json=WITH_EMAIL)
    assert response.status_code == 200
    body = response.json()
    assert body["pii_redacted"] == ["EMAIL"]
    assert "ana@example.com" not in json.dumps(body)


def test_metrics_count_pii_by_direction_and_type(api):
    api.post("/ask", json=WITH_EMAIL)
    counts = api.get("/metrics").json()["pii_detections"]
    assert counts["input"]["EMAIL"] >= 1


def test_production_refuses_to_start_without_pii_redaction():
    started = start(
        ENVIRONMENT="production", MODEL_PROVIDER="gateway",
        API_KEYS="a:" + "k" * 20, CF_ACCOUNT_ID="x", CF_API_TOKEN="y",
        PII_REDACTION="false",
    )
    assert started.returncode != 0
