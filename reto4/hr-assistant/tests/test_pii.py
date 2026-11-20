"""Pruebas del detector de PII."""

import pytest

from app.pii import mask_pii


@pytest.mark.parametrize(
    "text, kind",
    [
        ("mi correo es ana.lopez@empresa.com.mx", "email"),
        ("CURP GODE561231HDFRRN09 de Ana", "curp"),
        ("su RFC es LOPA800101AB1", "rfc"),
        ("tarjeta 4111 1111 1111 1111", "card"),
        ("NSS 12345678901", "nss"),
        ("llámale al 55 1234 5678", "phone"),
        ("teléfono +52 5512345678", "phone"),
    ],
)
def test_each_kind_is_masked_and_counted(text, kind):
    masked, found = mask_pii(text)
    assert found == {kind: 1}
    assert f"[{kind} oculto]" in masked


def test_text_without_pii_stays_the_same():
    text = "¿Quién trabaja en Tecnología? Busca EMP-0003 desde 2019-03-04"
    masked, found = mask_pii(text)
    assert masked == text
    assert not found


def test_several_values_are_all_masked():
    masked, found = mask_pii("a@b.com y c@d.org, RFC LOPA800101AB1")
    assert found == {"email": 2, "rfc": 1}
    assert "@" not in masked
