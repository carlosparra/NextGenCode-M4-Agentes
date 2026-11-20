"""Pruebas de ``app.pii``: deteccion de PII con regex y Luhn.

Cada tipo de PII tiene un caso positivo y uno negativo. Los datos del
directorio (nombre, ``EMP-0001``, departamento, fechas) nunca se ocultan.

:seealso: ``spec/05-security-hardening.md``
"""

import json

import pytest

from app.pii import redact_pii
from tests.conftest import SAMPLE_EMPLOYEES


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("Escribe a ana@empresa.com", "email"),
        ("Llama al 55 1234 5678", "phone"),
        ("Llama al +52 55-1234-5678", "phone"),
        ("Llama al 5512345678", "phone"),
        ("Pago con 4111 1111 1111 1111", "card"),
        ("Su CURP es GODE561231MDFRRS09", "curp"),
        ("Su RFC es GODE561231AB1", "rfc"),
    ],
)
def test_each_kind_of_pii_is_redacted(text, kind):
    """Cada tipo se reemplaza por su marca y se reporta solo una vez."""
    result = redact_pii(text)
    assert f"[REDACTED:{kind}]" in result.text
    assert result.kinds == [kind]


@pytest.mark.parametrize(
    "text",
    [
        "Escribe a ana arroba empresa",
        "El codigo es 551234567",
        "Ingreso el 2019-03-04",
        "Tarjeta 4111 1111 1111 1112",
        "Su CURP es GODE561231MDFRRS0",
    ],
)
def test_lookalikes_of_pii_are_not_redacted(text):
    """Un correo sin arroba, 9 digitos, una fecha, una tarjeta que no
    pasa Luhn (tampoco como telefono) y un CURP de 17 caracteres no se
    tocan."""
    result = redact_pii(text)
    assert result.text == text
    assert not result.kinds


def test_directory_data_is_never_redacted():
    """Nombres, ids, departamentos y el JSON de un empleado salen intactos."""
    employee_json = json.dumps(SAMPLE_EMPLOYEES[0], ensure_ascii=False)
    for text in ("EMP-0001", "Ana López", "Jorge Díaz", "Tecnología", employee_json):
        result = redact_pii(text)
        assert result.text == text
        assert not result.kinds


def test_mixed_pii_reports_each_kind_once_and_redaction_is_idempotent():
    """Varios tipos dan ``kinds`` sin repetir y limpiar dos veces no cambia nada."""
    text = "Correo ana@empresa.com o luis@empresa.com, telefono 55 1234 5678"
    first = redact_pii(text)
    assert "ana@empresa.com" not in first.text
    assert "luis@empresa.com" not in first.text
    assert sorted(first.kinds) == ["email", "phone"]
    second = redact_pii(first.text)
    assert second.text == first.text
    assert not second.kinds
