"""Pruebas unitarias del límite por cliente (``app.ratelimit``, ADR 0010).

El reloj es falso: el tiempo avanza solo cuando la prueba lo pide.
"""

from conftest import FakeClock

from app.ratelimit import RateLimiter


def test_limit_is_exact_and_retry_after_is_rounded_up_to_at_least_one():
    clock = FakeClock()
    limiter = RateLimiter(2, clock)

    assert limiter.check("acme") is None
    clock.advance(0.5)
    assert limiter.check("acme") is None
    clock.advance(9.8)
    assert limiter.check("acme") == 50
    clock.advance(49.2)
    assert limiter.check("acme") == 1


def test_window_slides_and_a_rejection_does_not_use_quota():
    clock = FakeClock()
    limiter = RateLimiter(1, clock)

    assert limiter.check("acme") is None
    clock.advance(30)
    assert limiter.check("acme") == 30
    assert limiter.check("globex") is None
    clock.advance(31)
    assert limiter.check("acme") is None
    assert limiter.check("acme") == 60
