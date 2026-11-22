"""Pruebas del filtro de salida a través de ``POST /ask`` con un modelo guionado."""

import json


def _ask_with_answer(make_observed, scripted_model, answer, environ=None):
    """Hace una pregunta sin PII a un modelo que responde ``answer``.

    :return: Aplicación observada y respuesta HTTP
    :rtype: tuple
    """
    model = scripted_model([json.dumps({"answer": answer})])
    observed = make_observed(environ=environ, model=model)
    response = observed.client.post("/ask", json={"question": "¿Quién es EMP-0001?"})
    return observed, response


def test_email_split_by_html_tags_is_still_redacted(make_observed, scripted_model):
    observed, response = _ask_with_answer(
        make_observed, scripted_model, "Escribe a ana<b>@</b>example.com"
    )

    body = response.json()
    assert response.status_code == 200
    assert body["answer"] == "Escribe a [EMAIL]"
    assert body["pii_redacted"] == []
    [event] = observed.events("pii_detected")
    assert (event["direction"], event["types"]) == ("output", ["EMAIL"])
    assert "ana@example.com" not in observed.log_text()


def test_disabled_redaction_still_strips_html_and_cuts_the_answer(
    make_observed, scripted_model
):
    environ = {"PII_REDACTION": "false", "MAX_ANSWER_CHARS": "10"}

    observed, response = _ask_with_answer(
        make_observed, scripted_model, "<i>ana@example.com es el correo</i>", environ
    )

    assert response.status_code == 200
    assert response.json()["answer"] == "ana@exampl"
    assert observed.events("pii_detected") == []
