"""Unit tests for API key parsing, authentication and the rate limiter."""

from datetime import timedelta

import pytest

from conftest import FakeClock

from app.security import RateLimiter, authenticate, parse_api_keys


def test_several_clients_are_parsed_with_spaces_trimmed():
    keys = parse_api_keys(" ana : key-one-0123456789 , bob:key-two-0123456789 ")
    assert keys == {"ana": "key-one-0123456789", "bob": "key-two-0123456789"}


def test_empty_key_list_gives_no_clients():
    assert not parse_api_keys("")


def test_key_may_contain_a_colon():
    assert parse_api_keys("ana:part1:part2") == {"ana": "part1:part2"}


@pytest.mark.parametrize("raw", [
    "no-separator-here",
    ":only-a-key-0123456789",
    "ana:",
    "ana:key-one-0123456789,ana:key-two-0123456789",
])
def test_malformed_key_list_is_rejected(raw):
    with pytest.raises(ValueError):
        parse_api_keys(raw)


def test_malformed_entry_error_gives_the_length_but_not_the_value():
    with pytest.raises(ValueError) as error:
        parse_api_keys("ana:valid-key-0123456789,SECRETVALUE")
    message = str(error.value)
    assert "SECRETVALUE" not in message
    assert "valid-key-0123456789" not in message
    assert "11" in message


def test_authenticate_returns_the_client_name():
    keys = {"ana": "abcdefgh12345678", "bob": "abcdefgh12345679"}
    assert authenticate(keys, "abcdefgh12345679") == "bob"


@pytest.mark.parametrize("received", [None, "", "abcdefgh1234567", "nope"])
def test_authenticate_rejects_missing_and_unknown_keys(received):
    assert authenticate({"ana": "abcdefgh12345678"}, received) is None


def test_requests_up_to_the_limit_pass_and_the_next_one_waits():
    clock = FakeClock(step_ms=0)
    limiter = RateLimiter(2, clock)
    assert limiter.check("ana") is None
    assert limiter.check("ana") is None
    wait = limiter.check("ana")
    assert 1 <= wait <= 60


def test_limits_are_independent_per_client():
    limiter = RateLimiter(1, FakeClock(step_ms=0))
    assert limiter.check("ana") is None
    assert limiter.check("ana") is not None
    assert limiter.check("bob") is None


def test_limit_is_released_in_the_next_minute():
    clock = FakeClock(step_ms=0)
    limiter = RateLimiter(1, clock)
    limiter.check("ana")
    assert limiter.check("ana") is not None
    clock._current += timedelta(seconds=61)  # pylint: disable=protected-access
    assert limiter.check("ana") is None
