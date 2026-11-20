"""Reloj inyectable: el unico lugar del producto donde se lee la hora.

El resto del codigo recibe un ``Clock`` para que las pruebas usen uno falso y
sean deterministas.
"""

import time
from datetime import datetime, timezone
from typing import Protocol


class Clock(Protocol):
    """Protocolo de reloj que usa la aplicacion."""

    def now(self) -> datetime:
        """Devuelve la hora actual con zona horaria UTC.

        :return: Hora actual en UTC
        :rtype: datetime.datetime
        """

    def monotonic(self) -> float:
        """Devuelve un contador monotono en segundos para medir duraciones.

        :return: Segundos de un contador que nunca retrocede
        :rtype: float
        """


class SystemClock:
    """Reloj real del sistema."""

    def now(self) -> datetime:
        """Devuelve la hora actual en UTC.

        :return: Hora actual con zona UTC
        :rtype: datetime.datetime
        """
        return datetime.now(timezone.utc)

    def monotonic(self) -> float:
        """Devuelve el contador monotono del sistema.

        :return: Segundos del contador monotono
        :rtype: float
        """
        return time.monotonic()
