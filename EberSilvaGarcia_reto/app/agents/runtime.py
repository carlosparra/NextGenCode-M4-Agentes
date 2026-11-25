"""Contexto de una corrida, compartido por el agente principal y los subagentes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.llm.costs import LlmSession
from app.observability.logs import JsonLogger


@dataclass
class RunContext:
    """Lo que una corrida necesita y que no vive en el estado del grafo.

    :param llm: Sesión con el modelo (cuenta tokens y costo de toda la corrida)
    :type llm: LlmSession
    :param logger: Log estructurado
    :type logger: JsonLogger
    :param as_of: Fecha de corte para antigüedad y vacaciones
    :type as_of: date
    :param request_id: Correlation id de la petición
    :type request_id: str
    :param compact: Prompts y observaciones compactos (palanca de costo)
    :type compact: bool
    :param scope_employee: Único empleado que un subagente puede consultar
    :type scope_employee: str | None
    :param details: Reportes estructurados de los subagentes
    :type details: dict
    """

    llm: LlmSession
    logger: JsonLogger
    as_of: date
    request_id: str
    compact: bool = True
    scope_employee: str | None = None
    details: dict = field(default_factory=dict)

    def audit(self, action: str, **fields: Any) -> None:
        """Registra una acción en la auditoría.

        :param action: Acción
        :type action: str
        """
        self.logger.audit(action, **fields)
