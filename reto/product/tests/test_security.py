"""Pruebas de claves por cliente, limite de peticiones, compliance y configuracion."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from conftest import GATEWAY_ENV, TEST_API_KEY, ManualClock
from app.auth import ApiKeyAuthenticator, parse_api_keys
from app.compliance import enforce, production_violations
from app.config import ConfigError
from app.ratelimit import RateLimiter


def test_api_keys_are_split_into_clients_at_the_first_colon():
    assert not tuple(parse_api_keys(""))

    pairs = parse_api_keys(" ana : key:with:colons , bob:second-key ")

    assert [tuple(pair) for pair in pairs] == [
        ("ana", "key:with:colons"),
        ("bob", "second-key"),
    ]


@pytest.mark.parametrize(
    "raw",
    ["ana:secret-one,ana:secret-two", "bad name:secret-three"],
    ids=["repeated client", "client with a space"],
)
def test_invalid_api_keys_are_rejected_without_showing_the_key(raw):
    with pytest.raises(ConfigError) as error:
        parse_api_keys(raw)

    assert "secret" not in str(error.value)


def test_authenticator_returns_the_client_only_for_a_matching_key():
    authenticator = ApiKeyAuthenticator(parse_api_keys("ana:ana-key-1234567890"))

    assert authenticator.authenticate(None) is None
    assert authenticator.authenticate("") is None
    assert authenticator.authenticate("clave-ñandú-incorrecta") is None
    assert authenticator.authenticate("ana-key-123456789") is None
    assert authenticator.authenticate("ana-key-1234567890") == "ana"


def test_rate_limit_window_slides_and_retry_after_is_rounded_up():
    clock = ManualClock(start=1000.0)
    limiter = RateLimiter(2, clock)

    assert limiter.check("ana").allowed
    clock.advance(30.5)
    assert limiter.check("ana").allowed

    clock.advance(14.7)  # 1045.2: la mas antigua sale en 14.8 s
    rejected = limiter.check("ana")
    assert (rejected.allowed, rejected.retry_after) == (False, 15)

    clock.advance(15.8)  # 1061: la de 1000 ya salio; la rechazada no cuenta
    assert limiter.check("ana").allowed
    assert limiter.check("ana").retry_after == 30  # 1030.5 + 60 - 1061 = 29.5

    clock.advance(29.2)  # faltan 0.3 s: nunca se responde 0
    assert limiter.check("ana").retry_after == 1


def test_concurrent_requests_never_exceed_the_limit():
    limiter = RateLimiter(50, ManualClock())

    with ThreadPoolExecutor(max_workers=8) as pool:
        decisions = list(pool.map(lambda _: limiter.check("ana"), range(200)))

    assert sum(decision.allowed for decision in decisions) == 50


def test_compliance_reports_every_broken_rule_only_in_production(make_settings):
    development = make_settings(API_KEYS="")
    assert production_violations(development) == []
    enforce(development)

    short_key = "k" * 15
    unsafe = make_settings(
        ENVIRONMENT="production",
        API_KEYS=f"ana:{short_key}",
        LANGSMITH_TRACING="true",
        LANGSMITH_API_KEY="lsv2-test-key",
        HIDE_INPUTS="false",
    )
    assert len(production_violations(unsafe)) == 3
    with pytest.raises(ConfigError) as error:
        enforce(unsafe)
    assert short_key not in str(error.value)

    border = make_settings(
        **GATEWAY_ENV, ENVIRONMENT="production", API_KEYS="ana:" + "k" * 16
    )
    assert production_violations(border) == []


def test_settings_validate_environment_and_rate_limit_and_hide_the_keys(
    make_settings,
):
    settings = make_settings()
    assert settings.environment == "development"
    assert settings.rate_limit_per_minute == 30

    for bad in ({"ENVIRONMENT": "staging"}, {"RATE_LIMIT_PER_MINUTE": "0"}):
        with pytest.raises(ConfigError):
            make_settings(**bad)

    assert TEST_API_KEY not in repr(settings)
