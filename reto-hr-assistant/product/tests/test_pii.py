"""Pruebas del detector de PII (``app.pii.redact``).

``redact(text)`` devuelve ``(texto_redactado, tipos)``: los tipos son una lista sin
duplicados y nunca traen los valores encontrados.
"""

import importlib

EMAIL = "ana@example.com"
PHONE = "55 1234 5678"
CURP = "LOPA900101MDFRNN09"
RFC = "GODE561231GR8"
VALID_CARD = "4111111111111111"
INVALID_CARD = "4111111111111112"


def redact(text):
    """Llama a ``app.pii.redact``; se importa aquí para que cada prueba falle sola.

    :param text: Texto a revisar
    :type text: str
    :return: Texto redactado y tipos encontrados
    :rtype: tuple[str, list[str]]
    """
    return importlib.import_module("app.pii").redact(text)


def test_every_pii_type_is_replaced_by_its_marker():
    text = (
        f"Correo {EMAIL}, tel {PHONE}, CURP {CURP}, RFC {RFC}, "
        f"tarjeta {VALID_CARD}, otra vez {EMAIL}"
    )

    redacted, types = redact(text)

    for value in (EMAIL, PHONE, CURP, RFC, VALID_CARD):
        assert value not in redacted
    for marker in ("[EMAIL]", "[PHONE]", "[CURP]", "[RFC]", "[CARD]"):
        assert marker in redacted
    assert sorted(types) == ["CARD", "CURP", "EMAIL", "PHONE", "RFC"]


def test_phone_with_spaces_dashes_or_country_code_is_detected():
    for phone in ("5512345678", "55 1234 5678", "55-1234-5678", "+52 55 1234 5678"):
        redacted, types = redact(f"llámame al {phone} hoy")

        assert types == ["PHONE"], phone
        assert redacted == "llámame al [PHONE] hoy"


def test_card_number_is_only_detected_when_it_passes_luhn():
    valid_text, valid_types = redact(f"mi tarjeta es {VALID_CARD}")
    invalid_text, invalid_types = redact(f"mi tarjeta es {INVALID_CARD}")

    assert (valid_text, valid_types) == ("mi tarjeta es [CARD]", ["CARD"])
    assert (invalid_text, invalid_types) == (f"mi tarjeta es {INVALID_CARD}", [])


def test_curp_is_not_also_reported_as_rfc():
    redacted, types = redact(f"Mi CURP es {CURP}")

    assert redacted == "Mi CURP es [CURP]"
    assert types == ["CURP"]
