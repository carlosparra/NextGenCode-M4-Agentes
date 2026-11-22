"""Usuarios de Locust para la prueba de carga (los corre ``verification.load``).

Cada usuario pregunta a ``POST /ask`` y registra el resultado con el código HTTP
en el nombre (``POST /ask [200]``, ``[429]``...), para contar cada resultado por
separado. La clave llega por la variable ``LOAD_API_KEY``; nunca se imprime.
"""

import os
import random
import ssl
import time

import httpx

# Locust solo existe cuando se corre con `uv run --with locust`
from locust import User, between, task  # pylint: disable=import-error

from verification import load

KEY = os.environ.get("LOAD_API_KEY", "")
WAIT = between(
    float(os.environ.get("LOAD_WAIT_MIN", "1")),
    float(os.environ.get("LOAD_WAIT_MAX", "2")),
)
ASK_TIMEOUT = 90


class Asker(User):
    """Una persona que le hace preguntas al asistente."""

    wait_time = WAIT
    http = None

    def on_start(self):
        """Abre el cliente HTTP del usuario."""
        # httpx usa certifi por omisión; el contexto del sistema confía en los
        # certificados de Windows (redes que interceptan TLS). truststore no sirve
        # aquí: choca con gevent, que Locust usa para la red.
        self.http = httpx.Client(
            base_url=self.host, timeout=ASK_TIMEOUT,
            verify=ssl.create_default_context(),
        )

    def on_stop(self):
        """Cierra el cliente HTTP del usuario."""
        self.http.close()

    @task
    def ask(self):
        """Hace una pregunta y registra el resultado en Locust."""
        question = load.pick_question(random)
        started = time.perf_counter()
        status, size, error = "error", 0, None
        try:
            response = self.http.post(
                "/ask", json={"question": question}, headers={"X-API-Key": KEY}
            )
            status, size = response.status_code, len(response.content)
            if status != 200:
                error = RuntimeError(f"HTTP {status}")
        except httpx.HTTPError as problem:
            error = problem
        self.environment.events.request.fire(
            request_type="POST", name=load.request_name(status),
            response_time=(time.perf_counter() - started) * 1000,
            response_length=size, exception=error, context={},
        )
