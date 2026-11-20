"""Metricas en memoria de este proceso.

Cuenta peticiones y errores 5xx, guarda una ventana acotada de
latencias para calcular p50 y p95 (rango mas cercano), suma tokens
y costo en USD, y dice si se cumple el SLO de latencia. Son estado operativo del
proceso: se reportan con su ``pid`` y se pierden al reiniciar. Desde el
reto de seguridad cuenta ademas los eventos ``security`` por control.

:seealso: ``spec/02-observability.md``, punto 3, ADR 0005 y
    ``spec/05-security-hardening.md``, punto 7.
"""

from __future__ import annotations

import math
import os
import threading
from collections import deque
from typing import Any

DEFAULT_WINDOW = 1000
SERVER_ERROR_STATUS = 500
# Controles de seguridad: siempre presentes en ``security``, en 0 al inicio.
SECURITY_CONTROLS = ("pii", "secret", "output_invalid", "tool_args", "injection")
# Spec 06: especialistas y motivos del supervisor, en 0 al inicio.
SPECIALISTS = ("directory", "policy")
SUPERVISOR_ROUTES = (
    "rule:employee",
    "rule:department",
    "rule:policy",
    # Adenda 1: id de empleado y tema de vacaciones.
    "rule:policy_employee",
    "model",
    "model_invalid",
)


def nearest_rank(values: list[float], percentile: float) -> float:
    """Calcula un percentil con el metodo de rango mas cercano.

    :param values: Valores sin ordenar.
    :type values: list[float]
    :param percentile: Percentil entre 0 y 100.
    :type percentile: float
    :return: El valor en la posicion ``ceil(p / 100 * n)``; 0 si no
        hay valores.
    :rtype: float
    """
    if not values:
        return 0
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile / 100 * len(ordered)))
    return ordered[rank - 1]


class Metrics:  # pylint: disable=too-many-instance-attributes
    """Metricas de peticiones, latencia, tokens y seguridad del proceso.

    :param slo_p95_ms: Meta de latencia p95 en milisegundos.
    :type slo_p95_ms: int
    :param window: Cantidad maxima de latencias guardadas.
    :type window: int
    """

    def __init__(self, slo_p95_ms: int, window: int = DEFAULT_WINDOW) -> None:
        """Inicializa contadores en cero.

        :param slo_p95_ms: Meta de latencia p95 en milisegundos.
        :type slo_p95_ms: int
        :param window: Cantidad maxima de latencias guardadas.
        :type window: int
        """
        self._slo_p95_ms = slo_p95_ms
        self._latencies: deque[float] = deque(maxlen=window)
        self._requests = 0
        self._errors = 0
        self._tokens = {"input": 0, "output": 0}
        self._cost_usd = 0.0
        self._security = dict.fromkeys(SECURITY_CONTROLS, 0)
        self._specialists = dict.fromkeys(SPECIALISTS, 0)
        self._supervisor = dict.fromkeys(SUPERVISOR_ROUTES, 0)
        self._lock = threading.Lock()

    def record_request(self, latency_ms: float, status: int) -> None:
        """Registra una peticion terminada.

        :param latency_ms: Latencia de la peticion en milisegundos.
        :type latency_ms: float
        :param status: Codigo HTTP de la respuesta.
        :type status: int
        """
        with self._lock:
            self._requests += 1
            if status >= SERVER_ERROR_STATUS:
                self._errors += 1
            self._latencies.append(latency_ms)

    def record_tokens(self, input_tokens: int, output_tokens: int) -> None:
        """Suma los tokens de una corrida del agente.

        :param input_tokens: Tokens de entrada.
        :type input_tokens: int
        :param output_tokens: Tokens de salida.
        :type output_tokens: int
        """
        with self._lock:
            self._tokens["input"] += input_tokens
            self._tokens["output"] += output_tokens

    def record_cost(self, cost_usd: float) -> None:
        """Suma el costo en USD de una respuesta.

        :param cost_usd: Costo de la respuesta, sin redondear.
        :type cost_usd: float
        """
        with self._lock:
            self._cost_usd += cost_usd

    def record_security(self, control: str) -> None:
        """Suma un evento de seguridad a su control.

        Cuenta uno por evento, no por tipo detectado.

        :param control: ``pii``, ``secret``, ``output_invalid``,
            ``tool_args`` o ``injection``.
        :type control: str
        """
        with self._lock:
            self._security[control] = self._security.get(control, 0) + 1

    def record_agents(self, specialist: str, route: str) -> None:
        """Suma una respuesta a su especialista y al motivo del supervisor.

        :param specialist: ``directory`` o ``policy``.
        :type specialist: str
        :param route: ``rule:employee``, ``rule:department``,
            ``rule:policy``, ``rule:policy_employee``, ``model`` o
            ``model_invalid``.
        :type route: str
        """
        with self._lock:
            self._specialists[specialist] = self._specialists.get(specialist, 0) + 1
            self._supervisor[route] = self._supervisor.get(route, 0) + 1

    def snapshot(self) -> dict[str, Any]:
        """Devuelve una foto de las metricas actuales.

        :return: ``pid``, ``requests``, ``error_rate``,
            ``latency_ms`` (p50 y p95), ``tokens``, ``cost_usd``
            acumulado, ``slo``, ``security`` (conteo por control),
            ``specialists`` (conteo por especialista) y ``supervisor``
            (conteo por motivo del supervisor).
        :rtype: dict[str, Any]
        """
        with self._lock:
            latencies = list(self._latencies)
            requests = self._requests
            errors = self._errors
            tokens = dict(self._tokens)
            cost_usd = self._cost_usd
            security = dict(self._security)
            specialists = dict(self._specialists)
            supervisor = dict(self._supervisor)
        p95 = nearest_rank(latencies, 95)
        return {
            "pid": os.getpid(),
            "requests": requests,
            "error_rate": errors / requests if requests else 0,
            "latency_ms": {"p50": nearest_rank(latencies, 50), "p95": p95},
            "tokens": tokens,
            "cost_usd": cost_usd,
            "slo": {
                "p95_ms_target": self._slo_p95_ms,
                "met": p95 < self._slo_p95_ms,
            },
            "security": security,
            "specialists": specialists,
            "supervisor": supervisor,
        }
