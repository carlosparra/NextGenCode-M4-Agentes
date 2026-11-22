"""Pruebas de la capa de PII en ``POST /ask``: modelo, log, auditoría y métricas."""

QUESTION_WITH_EMAIL = "mi correo es ana@example.com, ¿quién es EMP-0001?"
HISTORY_PHONE = "55 1234 5678"
TEST_CLIENT = "qa-tester"  # El cliente que arma ``conftest.with_test_key``.


def test_model_never_sees_personal_data_from_question_or_history(
    make_observed, scripted_model
):
    spy = scripted_model(['{"answer": "Listo."}'])
    observed = make_observed(model=spy)

    response = observed.client.post(
        "/ask",
        json={
            "question": QUESTION_WITH_EMAIL,
            "history": [
                {"role": "user", "content": f"llámame al {HISTORY_PHONE}"},
                {"role": "assistant", "content": "Claro."},
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["pii_redacted"] == ["EMAIL"]
    sent = " ".join(message["content"] for call in spy.calls for message in call)
    assert "[EMAIL]" in sent and "[PHONE]" in sent
    for value in ("ana@example.com", HISTORY_PHONE):
        assert value not in sent
        assert value not in observed.log_text()
    [event] = observed.events("pii_detected")
    assert event["request_id"] == response.json()["request_id"]
    assert event["client"] == TEST_CLIENT
    assert (event["direction"], event["types"]) == ("input", ["EMAIL"])


def test_metrics_count_each_type_once_per_detection(make_observed):
    observed = make_observed()
    observed.client.post(
        "/ask", json={"question": "escribe a ana@example.com o a luis@example.com"}
    )

    metrics = observed.client.get("/metrics").json()

    assert metrics["pii_detections"] == {"input": {"EMAIL": 1}, "output": {}}
