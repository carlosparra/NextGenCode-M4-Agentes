"""Tests of PII masking at the edges: log, errors, switch, config, compliance.

Only fictitious data is used: the CURP and the email are made up.
"""

import io
import json

import pytest

from conftest import (
    ANA_KEY, FakeClock, ScriptedModel, answer_json, log_lines, tool_call,
)
from app.compliance import check_production
from app.config import load_settings
from app.observability import JsonLogger

CURP = "AAAA010101HDFBBB09"
EMAIL = "persona.prueba@example.com"
BAD_HISTORY = {
    "question": "Hello",
    "history": [{"role": f"{CURP} {EMAIL}", "content": "stays text"}],
}
SAFE_PRODUCTION = {
    "API_KEYS": f"ana:{ANA_KEY}",
    "ENVIRONMENT": "production",
    "MODEL_PROVIDER": "gateway",
    "CF_ACCOUNT_ID": "acct",
    "CF_API_TOKEN": "token-value-2",
}


def test_log_line_with_non_ascii_text_is_valid_json_and_masked():
    stream = io.StringIO()
    logger = JsonLogger("hr-assistant", FakeClock(), stream)
    logger.log(
        "note",
        text=f"Señor José {EMAIL} y {CURP} 日本",
        glued=f"ñ{EMAIL}",
        multiline=f"line\n{EMAIL}\nline\n{CURP}",
        nested={"items": [EMAIL, {"curp": CURP.lower()}]},
    )
    raw = stream.getvalue()
    entry = json.loads(raw)
    assert not any(value in raw for value in (EMAIL, CURP, CURP.lower()))
    assert "[EMAIL]" in entry["text"] and "[CURP]" in entry["text"]
    assert "[EMAIL]" in entry["multiline"] and "[CURP]" in entry["multiline"]
    assert entry["nested"]["items"] == ["[EMAIL]", {"curp": "[CURP]"}]


def test_question_length_is_checked_with_the_original_text(make_observed_client):
    model = ScriptedModel([answer_json("Done.")])
    client, _ = make_observed_client(model=model, env={"MAX_QUESTION_CHARS": "20"})
    response = client.post("/ask", json={"question": f"{CURP} {EMAIL}"})
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid question length"}
    assert not model.calls


def test_validation_error_masks_only_the_pii_it_echoes(make_observed_client):
    masked_client, _ = make_observed_client()
    open_client, _ = make_observed_client(env={"PII_MASKING": "false"})
    masked = masked_client.post("/ask", json=BAD_HISTORY)
    original = open_client.post("/ask", json=BAD_HISTORY)
    assert masked.status_code == original.status_code == 422
    assert CURP in original.text and EMAIL in original.text
    expected = original.text.replace(CURP, "[CURP]").replace(EMAIL, "[EMAIL]")
    assert masked.json() == json.loads(expected)


def test_invalid_json_body_is_a_422_that_does_not_echo_the_pii(
    make_observed_client,
):
    client, _ = make_observed_client()
    response = client.post(
        "/ask", content=f'{{"question": "{CURP} {EMAIL}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert CURP not in response.text and EMAIL not in response.text


def test_masking_off_in_development_turns_off_all_three_layers(
    make_observed_client,
):
    model = ScriptedModel([
        tool_call("get_employee", employee_id=EMAIL),
        answer_json(f"Your data is {CURP}"),
    ])
    client, stream = make_observed_client(
        model=model, env={"PII_MASKING": "false"}
    )
    response = client.post("/ask", json={"question": f"My CURP is {CURP}"})
    assert response.status_code == 200
    assert CURP in json.dumps(model.calls)
    assert response.json()["answer"] == f"Your data is {CURP}"
    assert EMAIL in stream.getvalue()
    assert not [line for line in log_lines(stream)
                if line.get("action") == "pii_masked"]


def test_no_pii_means_no_pii_masked_event(make_observed_client):
    model = ScriptedModel([answer_json("EMP-0004 is Jorge Diaz.")])
    client, stream = make_observed_client(model=model)
    response = client.post("/ask", json={"question": "Who is EMP-0004?"})
    assert response.status_code == 200
    assert response.json()["answer"] == "EMP-0004 is Jorge Diaz."
    assert not [line for line in log_lines(stream)
                if line.get("action") == "pii_masked"]


def test_pii_masking_is_on_by_default_and_must_be_a_boolean():
    assert load_settings({}).pii_masking is True
    assert load_settings({"PII_MASKING": "false"}).pii_masking is False
    with pytest.raises(ValueError):
        load_settings({"PII_MASKING": "maybe"})


def test_production_rule_names_pii_masking_and_development_ignores_it():
    off = {**SAFE_PRODUCTION, "PII_MASKING": "false"}
    found = check_production(load_settings(off))
    assert len(found) == 1
    assert "PII_MASKING" in found[0]
    assert not check_production(load_settings(SAFE_PRODUCTION))
    assert not check_production(load_settings({"PII_MASKING": "false"}))
