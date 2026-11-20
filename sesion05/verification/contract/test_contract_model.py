"""Contrato de la sesión 5: el producto le explica el protocolo a un modelo real."""

import json
from pathlib import Path

SPEC = Path(__file__).resolve().parents[2] / "spec"
TOOL_PREFIX = "Resultado de la herramienta"
CAP = "No pude completar la respuesta"


def ask(gateway, question):
    return gateway.client.post("/ask", json={"question": question}).json()


def test_every_request_starts_with_the_system_instructions(gateway_product):
    body = ask(gateway_product, "¿Quién es EMP-0001?")
    assert "Ana López" in body["answer"]
    departments = {
        e["department"] for e in json.loads((SPEC / "employees.json").read_text("utf-8"))
    }
    for sent in gateway_product.requests("EMP-0001"):
        system = sent["messages"][0]
        assert system["role"] == "system"
        for name in ("get_employee", "search_by_department", *departments):
            assert name in system["content"]
        assert TOOL_PREFIX not in system["content"]


def test_a_small_model_that_mixes_formats_still_gets_its_tool_run(gateway_product):
    body = ask(gateway_product, "¿Quién es EMP-0004?")
    assert "Jorge Díaz" in body["answer"]
    assert body["tools_used"] == ["get_employee"]
    assert body["steps"] == 2


def test_unusable_output_is_corrected_instead_of_repeated(gateway_product):
    body = ask(gateway_product, "¿Quién es EMP-0002?")
    first, second = gateway_product.requests("EMP-0002")
    assert body["answer"] == "Recuperado"
    assert second["messages"] != first["messages"]
    assert len(second["messages"]) > len(first["messages"])
    assert second["messages"][-1]["role"] == "user"


def test_a_model_that_never_answers_well_ends_with_the_step_cap(gateway_product):
    body = ask(gateway_product, "¿Quién es EMP-0003?")
    assert CAP in body["answer"]
    assert body["steps"] == len(gateway_product.requests("EMP-0003"))
