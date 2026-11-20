"""Reloj inyectable del HR Assistant.

``SystemClock`` es la unica pieza del producto que lee el reloj real.
El resto de los modulos recibe un ``Clock`` inyectado, de modo que
las pruebas pueden usar un reloj falso y ser deterministas.

:seealso: ``spec/02-observability.md``, seccion Reglas.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Protocol


class Clock(Protocol):
    """Interfaz de un reloj: hora UTC y contador monotono."""

    def now(self) -> datetime:
        """Devuelve la hora actual con zona horaria UTC.

        :return: Instante actual en UTC.
        :rtype: datetime.datetime
        """

    def monotonic(self) -> float:
        """Devuelve segundos de un contador que nunca retrocede.

        :return: Segundos del contador monotono.
        :rtype: float
        """


class SystemClock:
    """Reloj real del sistema operativo."""

    def now(self) -> datetime:
        """Devuelve la hora actual del sistema en UTC.

        :return: Instante actual con zona horaria UTC.
        :rtype: datetime.datetime
        """
        return datetime.now(timezone.utc)

    def monotonic(self) -> float:
        """Devuelve el contador monotono del sistema.

        :return: Segundos de ``time.monotonic()``.
        :rtype: float
        """
        return time.monotonic()
