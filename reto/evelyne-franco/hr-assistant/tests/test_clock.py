"""Pruebas unitarias del reloj del sistema.

``SystemClock`` es la unica pieza que lee el reloj real; el resto del
producto lo recibe inyectado.
"""

from app.clock import SystemClock


def test_system_clock_returns_utc_time_and_monotonic_seconds():
    """``now()`` trae zona horaria UTC y ``monotonic()`` no retrocede."""
    clock = SystemClock()
    now = clock.now()
    assert now.tzinfo is not None
    assert now.utcoffset().total_seconds() == 0
    first = clock.monotonic()
    assert clock.monotonic() >= first
