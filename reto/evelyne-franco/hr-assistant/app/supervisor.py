"""Agente ``supervisor``: elige que especialista contesta.

Primero intenta con reglas en codigo, sin llamar al modelo, en este
orden:

0. Adenda 1: la pregunta trae un id y el tema de la politica es
   ``vacaciones`` -> ``policy`` (``rule:policy_employee``), con el
   primer id.
1. La pregunta trae un id ``EMP-dddd`` -> ``directory``
   (``rule:employee``).
2. La pregunta nombra un departamento del directorio, sin acentos ni
   mayusculas -> ``directory`` (``rule:department``).
3. La pregunta trae una palabra clave de una politica -> ``policy``
   (``rule:policy``).

Si ninguna aplica, hace **una** llamada a ``MODEL_SMALL``, sin
historial, con ``SUPERVISOR_PROMPT``. Una respuesta valida da
``model``; cualquier otra cosa, ``directory`` con ``model_invalid``.
Si el modelo no responde, ``ModelUnavailable`` sube y la API contesta
502, como siempre.

El supervisor solo ve el texto que ya limpio ``guard``.

:seealso: ``spec/06-multiagente.md``, punto 1.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from app.agent import parse_decision
from app.completion import Completion, Model
from app.employee_ids import EMPLOYEE_ID_PATTERN
from app.policies import PolicyBook
from app.prompts import SUPERVISOR_PROMPT
from app.text import fold_text
from app.tracing import Tracer

SPECIALIST_DIRECTORY = "directory"
SPECIALIST_POLICY = "policy"
SPECIALISTS = (SPECIALIST_DIRECTORY, SPECIALIST_POLICY)
ROUTE_EMPLOYEE = "rule:employee"
ROUTE_DEPARTMENT = "rule:department"
ROUTE_POLICY = "rule:policy"
ROUTE_POLICY_EMPLOYEE = "rule:policy_employee"
ROUTE_MODEL = "model"
ROUTE_MODEL_INVALID = "model_invalid"
# Adenda 1: tema de la politica que depende de la antiguedad.
VACATION_TOPIC = "vacaciones"


@dataclass(frozen=True)
class Decision:
    """Decision del supervisor.

    :param specialist: ``directory`` o ``policy``.
    :type specialist: str
    :param route: Motivo (``rule:employee``, ``rule:department``,
        ``rule:policy``, ``model`` o ``model_invalid``).
    :type route: str
    :param topic: Tema de la politica encontrada por ``rule:policy`` o
        ``rule:policy_employee``.
    :type topic: str | None
    :param completion: Respuesta del modelo si se le llamo.
    :type completion: app.completion.Completion | None
    :param employee_id: Id del empleado de ``rule:policy_employee``.
    :type employee_id: str | None
    """

    specialist: str
    route: str
    topic: str | None = None
    completion: Completion | None = None
    employee_id: str | None = None

    def summary(self) -> dict[str, str]:
        """Resumen sin texto, para trazas.

        :return: Especialista y motivo.
        :rtype: dict[str, str]
        """
        return {"specialist": self.specialist, "route": self.route}


def _names_department(folded: str, departments: Iterable[str]) -> bool:
    """Indica si el texto nombra un departamento (palabra completa).

    :param folded: Pregunta ya normalizada con ``fold_text``.
    :type folded: str
    :param departments: Departamentos del directorio.
    :type departments: collections.abc.Iterable[str]
    :return: ``True`` si aparece alguno.
    :rtype: bool
    """
    for department in departments:
        name = " ".join(fold_text(department).split())
        if name and re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", folded):
            return True
    return False


def route_by_rules(
    question: str, departments: Iterable[str], policies: PolicyBook
) -> Decision | None:
    """Aplica las reglas del supervisor, sin modelo.

    :param question: Pregunta ya limpia.
    :type question: str
    :param departments: Departamentos del directorio.
    :type departments: collections.abc.Iterable[str]
    :param policies: Libro de politicas.
    :type policies: app.policies.PolicyBook
    :return: La decision o ``None`` si ninguna regla aplica.
    :rtype: Decision | None
    """
    ids = EMPLOYEE_ID_PATTERN.findall(question)
    topic = policies.match_question(question)
    if ids and topic == VACATION_TOPIC:
        # Adenda 1: id y tema de vacaciones; se usa el primer id.
        return Decision(
            SPECIALIST_POLICY,
            ROUTE_POLICY_EMPLOYEE,
            topic=VACATION_TOPIC,
            employee_id=ids[0],
        )
    if ids:
        return Decision(SPECIALIST_DIRECTORY, ROUTE_EMPLOYEE)
    folded = " ".join(fold_text(question).split())
    if _names_department(folded, departments):
        return Decision(SPECIALIST_DIRECTORY, ROUTE_DEPARTMENT)
    if topic is not None:
        return Decision(SPECIALIST_POLICY, ROUTE_POLICY, topic=topic)
    return None


def parse_specialist(raw: str) -> str | None:
    """Lee el especialista de la respuesta del modelo.

    :param raw: Texto del modelo.
    :type raw: str
    :return: ``directory``, ``policy`` o ``None`` si no es valida.
    :rtype: str | None
    """
    data = parse_decision(raw)
    if data is None:
        return None
    specialist = data.get("specialist")
    return specialist if specialist in SPECIALISTS else None


class Supervisor:
    """Elige el especialista con reglas y, si no alcanzan, con el modelo.

    :param departments: Departamentos del directorio.
    :type departments: collections.abc.Iterable[str]
    :param policies: Libro de politicas.
    :type policies: app.policies.PolicyBook
    :param tracer: Trazador para la llamada al modelo.
    :type tracer: app.tracing.Tracer
    """

    def __init__(
        self, departments: Iterable[str], policies: PolicyBook, tracer: Tracer
    ) -> None:
        """Guarda los datos de las reglas y el trazador.

        :param departments: Departamentos del directorio.
        :type departments: collections.abc.Iterable[str]
        :param policies: Libro de politicas.
        :type policies: app.policies.PolicyBook
        :param tracer: Trazador.
        :type tracer: app.tracing.Tracer
        """
        self._departments = tuple(departments)
        self._policies = policies
        self._tracer = tracer

    def decide(
        self, question: str, model: Model, metadata: dict[str, str]
    ) -> Decision:
        """Decide el especialista de una pregunta.

        :param question: Pregunta ya limpia por ``guard``.
        :type question: str
        :param model: ``MODEL_SMALL``, solo si ninguna regla aplica.
        :type model: app.completion.Model
        :param metadata: ``request_id`` y ``client`` para la traza.
        :type metadata: dict[str, str]
        :return: Especialista, motivo, tema y la llamada al modelo.
        :rtype: Decision
        :raises app.completion.ModelUnavailable: Si el modelo falla.
        """
        decision = route_by_rules(question, self._departments, self._policies)
        if decision is not None:
            return decision
        complete = self._tracer.traceable(
            "llm", "llm", {**metadata, "model": model.name}
        )(model.complete)
        # Sin historial: solo el prompt de clasificacion y la pregunta.
        completion = complete(
            [
                {"role": "system", "content": SUPERVISOR_PROMPT},
                {"role": "user", "content": question},
            ]
        )
        specialist = parse_specialist(completion.text)
        if specialist is None:
            return Decision(
                SPECIALIST_DIRECTORY, ROUTE_MODEL_INVALID, completion=completion
            )
        return Decision(specialist, ROUTE_MODEL, completion=completion)
