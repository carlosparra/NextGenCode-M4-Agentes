"""Pruebas unitarias de las claves por cliente (``app.auth``).

``parse_api_keys`` interpreta ``API_KEYS`` (``cliente:clave,...``) y
``ApiKeyAuth.client_for`` devuelve el cliente de una clave o ``None``.
Un error nunca muestra el valor de la entrada mal formada.
"""

import pytest

from app.auth import ApiKeyAuth, parse_api_keys


def test_each_key_maps_to_its_client_and_unknown_keys_to_none():
    """Cada clave da su cliente; los espacios alrededor se ignoran y una
    clave equivocada, vacia o ausente no da ningun cliente.
    """
    auth = ApiKeyAuth(parse_api_keys(" acme:acme-key-1 , beta:beta-key-2 "))

    assert auth.client_for("acme-key-1") == "acme"
    assert auth.client_for("beta-key-2") == "beta"
    assert auth.client_for("wrong-key") is None
    assert auth.client_for("") is None
    assert auth.client_for(None) is None
    assert ApiKeyAuth(parse_api_keys("")).client_for("acme-key-1") is None


def test_malformed_api_keys_are_rejected():
    """Sin ``:``, con cliente vacio, con clave vacia o con una clave
    repetida, ``API_KEYS`` no se acepta.
    """
    for raw in (
        "no-colon-here",
        ":orphan-key",
        "acme:",
        "acme:same-key,beta:same-key",
    ):
        with pytest.raises(ValueError):
            parse_api_keys(raw)


def test_malformed_entry_error_names_its_position_and_length_but_never_its_value():
    """El mensaje dice que entrada falla (contando desde 1) y su largo,
    pero no su valor.
    """
    bad = "secret-value-without-client"

    with pytest.raises(ValueError) as error:
        parse_api_keys(f"acme:acme-key-1,{bad}")

    message = str(error.value)
    assert "API_KEYS" in message
    assert "entrada 2" in message
    assert str(len(bad)) in message
    assert bad not in message
    assert "secret" not in message
