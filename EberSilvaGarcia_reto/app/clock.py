"""Reloj inyectable: el código nunca llama ``datetime.now()`` directo.

Así las pruebas fijan la fecha (antigüedad, vacaciones, límite de peticiones)
y el comportamiento es determinista.
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone
from typing import Protocol


class Clock(Protocol):
    """Lo que el producto necesita saber del tiempo."""

    def now(self) -> datetime:
        """Fecha y hora actual en UTC."""

    def monotonic(self) -> float:
        """Segundos monotónicos, para medir latencias."""


class SystemClock:
    """El reloj real del sistema."""

    def now(self) -> datetime:
        """Fecha y hora actual en UTC.

        :return: Fecha y hora con zona UTC
        :rtype: datetime
        """
        return datetime.now(timezone.utc)

    def monotonic(self) -> float:
        """Segundos monotónicos.

        :return: Valor de ``time.perf_counter()``
        :rtype: float
        """
        return time.perf_counter()


class FixedClock:
    """Un reloj controlable para pruebas y demostraciones.

    :param start: Momento inicial
    :type start: datetime
    """

    def __init__(self, start: datetime) -> None:
        self._now = start
        self._mono = 0.0

    def now(self) -> datetime:
        """Momento actual del reloj.

        :return: Fecha y hora fijada
        :rtype: datetime
        """
        return self._now

    def monotonic(self) -> float:
        """Segundos monotónicos simulados.

        :return: Segundos acumulados con :meth:`advance`
        :rtype: float
        """
        return self._mono

    def advance(self, seconds: float) -> None:
        """Avanza el reloj.

        :param seconds: Segundos a avanzar
        :type seconds: float
        """
        self._now += timedelta(seconds=seconds)
        self._mono += seconds


def today(clock: Clock) -> date:
    """Fecha de hoy según el reloj inyectado.

    :param clock: Reloj
    :type clock: Clock
    :return: Fecha UTC
    :rtype: date
    """
    return clock.now().date()
