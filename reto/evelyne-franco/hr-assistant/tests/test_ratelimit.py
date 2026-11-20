"""Pruebas unitarias del limite de peticiones por cliente.

``RateLimiter(limit, clock)`` usa una ventana fija de 60 segundos por
cliente sobre ``clock.monotonic()``. ``check(client)`` devuelve una
decision con ``allowed`` y ``retry_after`` (segundos enteros, 1 o mas,
cuando no se permite). El reloj es manual: solo avanza cuando la prueba
lo dice.
"""

from app.ratelimit import RateLimiter


class ManualClock:
    """Reloj monotono que solo cambia con ``at``.

    :param start: Lectura inicial del reloj.
    :type start: float
    """

    def __init__(self, start=0.0):
        """Fija la lectura inicial.

        :param start: Lectura inicial del reloj.
        :type start: float
        """
        self._value = start

    def monotonic(self):
        """Devuelve la lectura actual, sin avanzar.

        :return: Segundos del contador.
        :rtype: float
        """
        return self._value

    def at(self, seconds):
        """Pone el reloj en ``seconds``.

        :param seconds: Nueva lectura del reloj.
        :type seconds: float
        """
        self._value = seconds


def test_the_request_after_the_limit_waits_the_rest_of_the_minute_rounded_up():
    """Con limite 2, la tercera peticion se niega y ``retry_after`` es lo
    que falta del minuto, redondeado hacia arriba y nunca menor que 1.
    """
    clock = ManualClock()
    limiter = RateLimiter(2, clock)

    assert limiter.check("acme").allowed
    clock.at(10.0)
    assert limiter.check("acme").allowed
    clock.at(10.5)
    refused = limiter.check("acme")
    assert not refused.allowed
    assert refused.retry_after == 50
    clock.at(59.9)
    assert limiter.check("acme").retry_after == 1


def test_the_window_resets_after_a_minute_and_each_client_has_its_own():
    """Un cliente sin cupo no afecta a otro, y al pasar 60 segundos el
    primero vuelve a tener cupo.
    """
    clock = ManualClock()
    limiter = RateLimiter(1, clock)

    assert limiter.check("acme").allowed
    assert not limiter.check("acme").allowed
    assert limiter.check("beta").allowed
    clock.at(60.0)
    assert limiter.check("acme").allowed
