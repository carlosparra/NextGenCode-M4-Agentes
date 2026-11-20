"""Agente ``guard``: el filtro de entrada de la spec 05.

Detecta inyeccion de instrucciones (solo se audita; la peticion sigue)
y oculta la PII de la pregunta y de cada valor del historial. Desde
aqui solo existe el texto limpio: el supervisor, el enrutador, el
modelo, el log y la traza nunca ven el original.

Desde la Adenda 1 de la spec 06, despues de ocultar la PII normaliza
los ids de empleado de la pregunta («empleado 004» -> ``EMP-0004``).

:seealso: ``spec/05-security-hardening.md`` y ``spec/06-multiagente.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.employee_ids import normalize_with_count
from app.guardrails import (
    CONTROL_INJECTION,
    CONTROL_PII,
    KIND_PHRASE,
    detect_injection,
)
from app.pii import merge_kinds, redact_pii
from app.security import STAGE_INPUT, Audit


@dataclass(frozen=True)
class GuardResult:
    """Entrada ya revisada por ``guard``.

    :param question: Pregunta limpia.
    :type question: str
    :param history: Historial limpio.
    :type history: list[dict[str, str]]
    :param kinds: Tipos de PII ocultados, sin repetir.
    :type kinds: list[str]
    :param injection: ``True`` si se detecto una frase de inyeccion.
    :type injection: bool
    """

    question: str
    history: list[dict[str, str]] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)
    injection: bool = False
    ids_normalized: int = 0

    def summary(self) -> dict[str, object]:
        """Resumen sin texto, para trazas.

        :return: Tipos de PII, si hubo inyeccion y cuantos ids se
            normalizaron (solo el conteo).
        :rtype: dict[str, object]
        """
        return {
            "pii_kinds": list(self.kinds),
            "injection": self.injection,
            "ids_normalized": self.ids_normalized,
        }


def redact_history(
    history: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[str]]:
    """Oculta la PII de cada valor del historial.

    :param history: Historial recibido.
    :type history: list[dict[str, str]]
    :return: Historial limpio y tipos ocultados, sin repetir.
    :rtype: tuple[list[dict[str, str]], list[str]]
    """
    found: list[list[str]] = []
    clean_history = []
    for message in history:
        clean_message = {}
        for key, value in message.items():
            result = redact_pii(str(value))
            found.append(result.kinds)
            clean_message[key] = result.text
        clean_history.append(clean_message)
    return clean_history, merge_kinds(*found)


def screen_input(
    question: str,
    history: list[dict[str, str]],
    audit: Audit,
    who: tuple[str, str],
) -> GuardResult:
    """Revisa la entrada: detecta inyeccion y oculta la PII.

    :param question: Pregunta ya validada.
    :type question: str
    :param history: Historial recibido.
    :type history: list[dict[str, str]]
    :param audit: Auditoria de seguridad.
    :type audit: app.security.Audit
    :param who: ``(request_id, client)`` de la peticion.
    :type who: tuple[str, str]
    :return: Pregunta limpia, historial limpio, tipos e inyeccion.
    :rtype: GuardResult
    """
    request_id, client = who
    texts = [question, *(str(m.get("content", "")) for m in history)]
    injection = any(detect_injection(text) for text in texts)
    if injection:
        audit.record(
            request_id, client, STAGE_INPUT, CONTROL_INJECTION, [KIND_PHRASE]
        )
    clean_question = redact_pii(question)
    clean_history, history_kinds = redact_history(history)
    kinds = merge_kinds(clean_question.kinds, history_kinds)
    if kinds:
        audit.record(request_id, client, STAGE_INPUT, CONTROL_PII, kinds)
    # Adenda 1: los ids escritos de otra forma se normalizan sobre el
    # texto ya limpio de PII; el historial no se toca.
    question_text, ids_normalized = normalize_with_count(clean_question.text)
    return GuardResult(
        question=question_text,
        history=clean_history,
        kinds=kinds,
        injection=injection,
        ids_normalized=ids_normalized,
    )
