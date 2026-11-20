"""Pruebas unitarias del modulo de configuracion.

Verifica que los valores por omision son correctos y que
las validaciones impiden arrancar con valores invalidos.
"""

import pytest

from app.config import Settings, load_settings


def test_default_settings_are_correct():
    """Los valores por omision coinciden con la especificacion:
    model_provider='fake', agent_max_steps=3,
    max_question_chars=2000.
    """
    s = Settings()
    assert s.model_provider == "fake"
    assert s.agent_max_steps == 3
    assert s.max_question_chars == 2000


def test_zero_max_steps_raises_error():
    """AGENT_MAX_STEPS=0 impide arrancar con error claro."""
    with pytest.raises((ValueError, Exception)):
        Settings(agent_max_steps=0)


# -- Sesion 2: observabilidad ---------------------------------------

def test_observability_settings_have_safe_defaults():
    """Sin variables de entorno: servicio ``hr-assistant``, SLO de
    2000 ms, trazas apagadas y entradas/salidas ocultas.
    """
    settings = load_settings({})
    assert settings.service_name == "hr-assistant"
    assert settings.slo_p95_ms == 2000
    assert settings.langsmith_tracing is False
    assert settings.hide_inputs is True
    assert settings.hide_outputs is True


def test_invalid_slo_target_stops_startup():
    """``SLO_P95_MS`` en 0 o con texto no numerico falla al arrancar."""
    with pytest.raises(ValueError):
        load_settings({"SLO_P95_MS": "0"})
    with pytest.raises(ValueError):
        load_settings({"SLO_P95_MS": "fast"})


def test_booleans_are_parsed_and_api_key_is_never_stored():
    """Los booleanos ``true``/``false`` se leen bien y la clave de
    LangSmith no queda guardada en la configuracion.
    """
    secret = "lsv2-secret-value"
    settings = load_settings(
        {
            "SERVICE_NAME": "hr-test",
            "LANGSMITH_TRACING": "true",
            "HIDE_INPUTS": "false",
            "HIDE_OUTPUTS": "false",
            "LANGSMITH_API_KEY": secret,
        }
    )
    assert settings.service_name == "hr-test"
    assert settings.langsmith_tracing is True
    assert settings.hide_inputs is False
    assert settings.hide_outputs is False
    assert secret not in repr(settings)
    assert secret not in str(settings.model_dump())


# -- Sesion 3: costos y modelo real -------------------------------------

CF_ENV = {
    "MODEL_PROVIDER": "gateway",
    "CF_ACCOUNT_ID": "acc-123",
    "CF_GATEWAY_ID": "gw-456",
    "CF_API_TOKEN": "cf-token-do-not-leak",
}


def test_cost_settings_have_the_documented_defaults():
    """Sin variables de entorno, los valores coinciden con la tabla de
    ``spec/03-costs.md``.
    """
    settings = load_settings({})

    assert settings.cf_account_id == ""
    assert settings.cf_gateway_id == "default"
    assert settings.cf_api_token.get_secret_value() == ""
    assert settings.model_small == "@cf/meta/llama-3.1-8b-instruct-fast"
    assert settings.model_large == "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    assert settings.routing is True
    assert settings.router_max_chars == 80
    assert settings.history_window == 6
    assert settings.model_max_tokens == 300
    assert settings.model_temperature == 0
    assert settings.cache_ttl_seconds == 0
    assert settings.prices_path == "data/model_prices.json"


def test_history_window_zero_is_allowed_but_invalid_numbers_stop_startup():
    """``HISTORY_WINDOW=0`` es valido; un negativo o un texto no
    numerico en las variables nuevas impide arrancar.
    """
    assert load_settings({"HISTORY_WINDOW": "0"}).history_window == 0
    assert load_settings({"ROUTING": "false"}).routing is False
    for name, value in (
        ("HISTORY_WINDOW", "-1"),
        ("ROUTER_MAX_CHARS", "many"),
        ("MODEL_MAX_TOKENS", "0"),
        ("MODEL_TEMPERATURE", "warm"),
        ("CACHE_TTL_SECONDS", "-5"),
    ):
        with pytest.raises(ValueError):
            load_settings({name: value})


def test_gateway_provider_requires_every_cloudflare_variable_and_hides_the_token():
    """Con ``MODEL_PROVIDER=gateway``, faltar cualquier ``CF_*``
    impide arrancar y el mensaje nombra la variable. Con las tres, el
    token no aparece en ``repr`` ni en ``model_dump``.
    """
    for missing in ("CF_ACCOUNT_ID", "CF_GATEWAY_ID", "CF_API_TOKEN"):
        env = {**CF_ENV, missing: ""}
        with pytest.raises(ValueError, match=missing):
            load_settings(env)

    settings = load_settings(CF_ENV)
    token = CF_ENV["CF_API_TOKEN"]
    assert settings.cf_api_token.get_secret_value() == token
    assert token not in repr(settings)
    assert token not in str(settings.model_dump())


# -- Sesion 4: produccion -------------------------------------------------

def test_production_settings_have_the_documented_defaults():
    """Sin variables: ``development``, 30 peticiones por minuto y sin claves."""
    settings = load_settings({})

    assert settings.environment == "development"
    assert settings.rate_limit_per_minute == 30
    assert not settings.api_keys


def test_invalid_environment_or_rate_limit_stops_startup():
    """Un ``ENVIRONMENT`` desconocido o ``RATE_LIMIT_PER_MINUTE`` en 0 o
    no numerico impiden arrancar.
    """
    for name, value in (
        ("ENVIRONMENT", "staging"),
        ("RATE_LIMIT_PER_MINUTE", "0"),
        ("RATE_LIMIT_PER_MINUTE", "many"),
    ):
        with pytest.raises(ValueError):
            load_settings({name: value})


def test_api_keys_never_appear_in_settings_or_startup_errors():
    """Las claves no salen en ``repr`` ni en ``model_dump``, y un
    ``API_KEYS`` mal formado falla sin mostrar su valor.
    """
    key = "acme-key-0123456789abcdef"
    settings = load_settings({"API_KEYS": f"acme:{key}"})
    assert settings.api_keys
    assert key not in repr(settings)
    assert key not in str(settings.model_dump())

    broken = "secret-value-without-client"
    with pytest.raises(ValueError) as error:
        load_settings({"API_KEYS": broken})
    assert broken not in str(error.value)
