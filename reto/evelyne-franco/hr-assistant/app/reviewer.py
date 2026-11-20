"""Agente ``reviewer``: valida la salida y la comprueba contra los datos.

Corre al final de cada peticion, en codigo y sin modelo:

1. ``screen_answer`` de la spec 05: secretos, PII y respuesta vacia.
2. Comprobacion contra los datos (spec 06, punto 4):

   - ``directory``: un id ``EMP-dddd`` que no existe en el directorio y
     que la persona no escribio reemplaza la respuesta por un mensaje
     fijo.
   - ``policy``: cada numero completo (``\\d+``) de la respuesta debe
     aparecer en el texto de alguna politica consultada; si no, la
     respuesta se cambia por la primera politica consultada o, si no se
     consulto ninguna, por un mensaje fijo. Desde la Adenda 1 tambien
     valen los numeros de ``vacation_days`` (por valor, sin ceros a la
     izquierda) y, si hubo ``vacation_days``, el reemplazo es la frase
     armada en codigo con su resultado (``vacation_sentence``).

3. ``truncate_answer``: el recorte a ``MAX_ANSWER_CHARS``.

Cada hallazgo se registra en la auditoria con ``stage=output``; un
reemplazo usa ``control=ungrounded`` y ``kinds`` ``employee_id`` o
``policy_number``, nunca el valor.

:seealso: ``spec/06-multiagente.md``, punto 4.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from app.employee_ids import EMPLOYEE_ID_PATTERN
from app.guardrails import screen_answer, truncate_answer
from app.security import STAGE_OUTPUT, Audit
from app.vacations import vacation_sentence

SPECIALIST_DIRECTORY = "directory"
SPECIALIST_POLICY = "policy"
CONTROL_UNGROUNDED = "ungrounded"
KIND_EMPLOYEE_ID = "employee_id"
KIND_POLICY_NUMBER = "policy_number"
DIRECTORY_UNVERIFIED = (
    "No pude verificar la respuesta con el directorio. Intenta de nuevo."
)
POLICY_UNVERIFIED = (
    "No pude verificar la respuesta con las políticas. Intenta de nuevo."
)
NUMBER_PATTERN = re.compile(r"\d+")


def ungrounded_ids(
    answer: str, question: str, known_ids: Iterable[str]
) -> list[str]:
    """Devuelve los ids de la respuesta sin respaldo.

    Un id no tiene respaldo si no existe en el directorio y la persona
    no lo escribio en su pregunta.

    :param answer: Respuesta del especialista.
    :type answer: str
    :param question: Pregunta ya limpia.
    :type question: str
    :param known_ids: Ids que existen en el directorio.
    :type known_ids: collections.abc.Iterable[str]
    :return: Ids sin respaldo, sin repetir y en orden de aparicion.
    :rtype: list[str]
    """
    allowed = set(known_ids) | set(EMPLOYEE_ID_PATTERN.findall(question))
    found = EMPLOYEE_ID_PATTERN.findall(answer)
    return list(dict.fromkeys(i for i in found if i not in allowed))


def _number_value(number: str) -> str:
    """Valor de un numero sin ceros a la izquierda (``0004`` -> ``4``).

    :param number: Digitos.
    :type number: str
    :return: El mismo numero sin ceros a la izquierda.
    :rtype: str
    """
    return str(int(number))


def allowed_numbers(
    policy_texts: Iterable[str],
    vacation_results: Iterable[Mapping[str, Any]] = (),
) -> tuple[set[str], set[str]]:
    """Numeros permitidos en una respuesta de ``policy``.

    Los de las politicas se comparan como cadena completa; los de
    ``vacation_days`` (dias, años, fecha, id y nota, Adenda 1) por valor,
    sin ceros a la izquierda.

    :param policy_texts: Textos de las politicas consultadas.
    :type policy_texts: collections.abc.Iterable[str]
    :param vacation_results: Resultados de ``vacation_days``.
    :type vacation_results: collections.abc.Iterable[collections.abc.Mapping]
    :return: Numeros de las politicas y valores de ``vacation_days``.
    :rtype: tuple[set[str], set[str]]
    """
    from_policies: set[str] = set()
    for text in policy_texts:
        from_policies.update(NUMBER_PATTERN.findall(text))
    from_vacations: set[str] = set()
    for result in vacation_results:
        for value in result.values():
            from_vacations.update(
                _number_value(n) for n in NUMBER_PATTERN.findall(str(value))
            )
    return from_policies, from_vacations


def ungrounded_numbers(
    answer: str,
    policy_texts: Iterable[str],
    vacation_results: Iterable[Mapping[str, Any]] = (),
) -> list[str]:
    """Devuelve los numeros de la respuesta sin respaldo.

    Los numeros se comparan completos: ``5`` no cuenta dentro de ``15``.
    Desde la Adenda 1 tambien valen los de ``vacation_days``.

    :param answer: Respuesta del especialista.
    :type answer: str
    :param policy_texts: Textos de las politicas consultadas.
    :type policy_texts: collections.abc.Iterable[str]
    :param vacation_results: Resultados de ``vacation_days``.
    :type vacation_results: collections.abc.Iterable[collections.abc.Mapping]
    :return: Numeros sin respaldo, sin repetir y en orden de aparicion.
    :rtype: list[str]
    """
    from_policies, from_vacations = allowed_numbers(policy_texts, vacation_results)
    found = NUMBER_PATTERN.findall(answer)
    return list(
        dict.fromkeys(
            n
            for n in found
            if n not in from_policies and _number_value(n) not in from_vacations
        )
    )


@dataclass(frozen=True)
class Review:
    """Resultado del revisor.

    :param text: Respuesta final, lista para devolver.
    :type text: str
    :param kinds: Tipos ocultados por la validacion (``redactions``).
    :type kinds: list[str]
    :param controls: Controles que encontraron algo, en orden.
    :type controls: list[str]
    :param replaced: ``True`` si la comprobacion contra los datos
        reemplazo la respuesta.
    :type replaced: bool
    """

    text: str
    kinds: list[str] = field(default_factory=list)
    controls: list[str] = field(default_factory=list)
    replaced: bool = False

    def summary(self) -> dict[str, object]:
        """Resumen sin texto, para trazas.

        :return: Controles y si hubo reemplazo.
        :rtype: dict[str, object]
        """
        return {"controls": list(self.controls), "replaced": self.replaced}


@dataclass(frozen=True)
class ReviewInput:
    """Lo que revisa el revisor de una peticion.

    :param answer: Respuesta del especialista.
    :type answer: str
    :param question: Pregunta ya limpia.
    :type question: str
    :param specialist: ``directory`` o ``policy``.
    :type specialist: str
    :param policy_texts: Textos de las politicas consultadas.
    :type policy_texts: list[str]
    :param request_id: Id de la peticion.
    :type request_id: str
    :param client: Cliente que pregunta.
    :type client: str
    :param vacation_results: Resultados de ``vacation_days`` de la
        peticion (Adenda 1).
    :type vacation_results: list[dict[str, Any]]
    """

    answer: str
    question: str
    specialist: str
    policy_texts: list[str] = field(default_factory=list)
    request_id: str = "-"
    client: str = "-"
    vacation_results: list[dict[str, Any]] = field(default_factory=list)


class Reviewer:
    """Valida la salida y la comprueba contra los datos.

    :param known_ids: Ids que existen en el directorio.
    :type known_ids: collections.abc.Iterable[str]
    :param audit: Auditoria de seguridad.
    :type audit: app.security.Audit
    :param secrets: Secretos que nunca salen en la respuesta.
    :type secrets: collections.abc.Iterable[str]
    :param max_answer_chars: Largo maximo de la respuesta.
    :type max_answer_chars: int
    """

    def __init__(
        self,
        known_ids: Iterable[str],
        audit: Audit,
        secrets: Iterable[str],
        max_answer_chars: int,
    ) -> None:
        """Guarda los datos y las dependencias del revisor.

        :param known_ids: Ids que existen en el directorio.
        :type known_ids: collections.abc.Iterable[str]
        :param audit: Auditoria de seguridad.
        :type audit: app.security.Audit
        :param secrets: Secretos conocidos.
        :type secrets: collections.abc.Iterable[str]
        :param max_answer_chars: Largo maximo de la respuesta.
        :type max_answer_chars: int
        """
        self._known_ids = frozenset(known_ids)
        self._audit = audit
        self._secrets = tuple(secrets)
        self._max_answer_chars = max_answer_chars

    def review(self, item: ReviewInput) -> Review:
        """Revisa una respuesta: validacion, datos y recorte.

        :param item: Respuesta, pregunta, especialista y politicas.
        :type item: ReviewInput
        :return: Respuesta final y resumen de controles.
        :rtype: Review
        """
        screened = screen_answer(item.answer, self._secrets)
        findings = list(screened.findings)
        text, replaced = self._ground(screened.text, item, findings)
        text, trim_findings = truncate_answer(text, self._max_answer_chars)
        findings.extend(trim_findings)
        for control, kinds in findings:
            self._audit.record(
                item.request_id, item.client, STAGE_OUTPUT, control, kinds
            )
        return Review(
            text=text,
            kinds=list(screened.kinds),
            controls=[control for control, _ in findings],
            replaced=replaced,
        )

    def _ground(
        self,
        text: str,
        item: ReviewInput,
        findings: list[tuple[str, list[str]]],
    ) -> tuple[str, bool]:
        """Comprueba la respuesta contra los datos del especialista.

        :param text: Respuesta ya revisada por ``screen_answer``.
        :type text: str
        :param item: Datos de la revision.
        :type item: ReviewInput
        :param findings: Hallazgos acumulados; aqui se agrega el reemplazo.
        :type findings: list[tuple[str, list[str]]]
        :return: Respuesta (quiza reemplazada) y si hubo reemplazo.
        :rtype: tuple[str, bool]
        """
        if item.specialist == SPECIALIST_POLICY:
            if not ungrounded_numbers(
                text, item.policy_texts, item.vacation_results
            ):
                return text, False
            findings.append((CONTROL_UNGROUNDED, [KIND_POLICY_NUMBER]))
            if item.vacation_results:
                # Adenda 1: respuesta armada en codigo con el calculo.
                return vacation_sentence(item.vacation_results[0]), True
            if item.policy_texts:
                return item.policy_texts[0], True
            return POLICY_UNVERIFIED, True
        if ungrounded_ids(text, item.question, self._known_ids):
            findings.append((CONTROL_UNGROUNDED, [KIND_EMPLOYEE_ID]))
            return DIRECTORY_UNVERIFIED, True
        return text, False
