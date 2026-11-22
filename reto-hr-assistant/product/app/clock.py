"""Reloj inyectable: el único lugar del producto que toca la hora real."""

import time
from datetime import datetime, timezone
from typing import Protocol


class Clock(Protocol):
    """Interfaz de reloj que reciben el log, el middleware y las métricas."""

    def now(self) -> datetime:
        """Devuelve la hora actual con zona horaria UTC.

        :return: Hora actual en UTC
        :rtype: datetime.datetime
        """

    def monotonic(self) -> float:
        """Devuelve segundos de un reloj que nunca retrocede.

        :return: Segundos desde un origen arbitrario
        :rtype: float
        """


class SystemClock:
    """Reloj real del sistema; las pruebas inyectan uno falso en su lugar."""

    def now(self) -> datetime:
        """Devuelve la hora actual del sistema en UTC.

        :return: Hora actual con ``tzinfo`` UTC
        :rtype: datetime.datetime
        """
        return datetime.now(timezone.utc)

    def monotonic(self) -> float:
        """Devuelve el valor del reloj monotónico del sistema.

        :return: Segundos desde un origen arbitrario
        :rtype: float
        """
        return time.monotonic()
