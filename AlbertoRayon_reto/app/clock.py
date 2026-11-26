"""Reloj inyectable: el producto nunca llama a ``datetime.now()`` por su cuenta."""

from datetime import datetime, timedelta, timezone


class SystemClock:
    """Reloj real, en UTC."""

    def now(self) -> datetime:
        """Devuelve la hora actual.

        :return: Fecha y hora en UTC
        :rtype: datetime.datetime
        """
        return datetime.now(timezone.utc)


class FixedClock:
    """Reloj detenido para pruebas; avanza solo cuando se le pide."""

    def __init__(self, start: datetime):
        self._now = start

    def now(self) -> datetime:
        """Devuelve la hora fijada.

        :return: Fecha y hora configuradas
        :rtype: datetime.datetime
        """
        return self._now

    def advance(self, seconds: float) -> None:
        """Adelanta el reloj.

        :param seconds: Segundos que avanza
        :type seconds: float
        """
        self._now += timedelta(seconds=seconds)
