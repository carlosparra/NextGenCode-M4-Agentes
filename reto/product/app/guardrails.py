"""Guardas de entrada y salida de ``POST /ask``.

Entrada: una pregunta o un mensaje del historial con inyeccion de
instrucciones se rechaza (``400 input rejected``); los datos sensibles se
enmascaran antes del modelo, el log y la traza (``PII_POLICY=mask``) o se
rechazan (``PII_POLICY=block``, ``400 sensitive data not allowed``).

Salida: la respuesta nunca va vacia, se recorta a ``MAX_ANSWER_CHARS``, se
enmascaran sus datos sensibles y, si trae un secreto, se reemplaza.

Cada guarda que actua deja un evento ``audit`` y suma su contador de
``security`` en ``/metrics``. Nunca se registra el valor detectado, la pregunta
ni la clave: solo el tipo y donde se encontro.
"""

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

from app import pii
from app.config import PII_POLICY_BLOCK
from app.metrics import (
    SECURITY_INPUTS_REJECTED,
    SECURITY_OUTPUTS_BLOCKED,
    SECURITY_PII_DETECTIONS,
)
from app.telemetry import (
    AUDIT_INPUT_REJECTED,
    AUDIT_OUTPUT_BLOCKED,
    AUDIT_PII_DETECTED,
)

INPUT_REJECTED_DETAIL = "input rejected"
SENSITIVE_DATA_DETAIL = "sensitive data not allowed"
EMPTY_ANSWER = "No encontré una respuesta."
BLOCKED_ANSWER = "No puedo mostrar esa respuesta."
WHERE_QUESTION = "question"
WHERE_HISTORY = "history"
WHERE_ANSWER = "answer"

# Se aplica sobre el texto en minusculas y sin acentos (ver ``_normalize``).
INJECTION_PATTERN = re.compile(
    r"\bignora\s+(?:todas\s+)?(?:las\s+)?instrucciones\b"
    r"|\bignore\s+(?:(?:all|the)\s+)?(?:(?:previous|above)\s+)?instructions\b"
    r"|\bprompt\s+del\s+sistema\b"
    r"|\bsystem\s+prompt\b"
    r"|\brevela\s+tus\s+instrucciones\b"
)
BEARER_PATTERN = re.compile(r"\bBearer\s+\S+", re.IGNORECASE)
# 32 o mas caracteres hexadecimales con al menos un digito y una letra: una
# palabra o un numero largos no son un token.
HEX_TOKEN_PATTERN = re.compile(
    r"\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{32,}\b", re.IGNORECASE
)
SECRET_PATTERNS = (BEARER_PATTERN, HEX_TOKEN_PATTERN)
COMBINING_MARK = "Mn"


class InputRejected(Exception):
    """La pregunta o el historial no pasan las guardas de entrada.

    :param detail: Texto fijo del ``400`` (nunca el contenido rechazado)
    :type detail: str
    """

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class OutputCheck:
    """Resultado de validar una respuesta.

    :param answer: Respuesta lista para devolver
    :type answer: str
    :param blocked: ``True`` si se reemplazo por traer un secreto
    :type blocked: bool
    """

    answer: str
    blocked: bool = False


@dataclass(frozen=True)
class GuardedInput:
    """Entrada ya revisada, lista para el enrutador, la cache y el agente.

    :param question: Pregunta con los datos sensibles enmascarados
    :type question: str
    :param history: Historial con los datos sensibles enmascarados
    :type history: list[dict]
    :param pii_types: Tipos de dato sensible encontrados en la entrada
    :type pii_types: tuple[str, ...]
    """

    question: str
    history: list
    pii_types: tuple = ()


@dataclass(frozen=True)
class GuardedOutput:
    """Respuesta ya revisada.

    :param answer: Respuesta validada y enmascarada
    :type answer: str
    :param blocked: ``True`` si se reemplazo por traer un secreto
    :type blocked: bool
    :param pii_types: Tipos de dato sensible encontrados en la respuesta
    :type pii_types: tuple[str, ...]
    """

    answer: str
    blocked: bool = False
    pii_types: tuple = ()


def _normalize(text: str) -> str:
    """Pasa un texto a minusculas y le quita los acentos.

    :param text: Texto original
    :type text: str
    :return: Texto normalizado para comparar patrones
    :rtype: str
    """
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(
        char for char in decomposed if unicodedata.category(char) != COMBINING_MARK
    )


def is_injection(text: str) -> bool:
    """Indica si un texto intenta inyectar instrucciones al modelo.

    No distingue mayusculas ni acentos.

    :param text: Pregunta o mensaje del historial
    :type text: str
    :return: ``True`` si coincide algun patron de inyeccion
    :rtype: bool
    """
    return INJECTION_PATTERN.search(_normalize(text)) is not None


def _leaks_secret(answer: str, secrets: Iterable[str]) -> bool:
    """Indica si una respuesta trae un secreto.

    :param answer: Respuesta a revisar
    :type answer: str
    :param secrets: Valores que nunca deben salir (las claves de ``API_KEYS``)
    :type secrets: collections.abc.Iterable[str]
    :return: ``True`` si trae una clave, un ``Bearer`` o un token hexadecimal
    :rtype: bool
    """
    if any(secret and secret in answer for secret in secrets):
        return True
    return any(pattern.search(answer) for pattern in SECRET_PATTERNS)


def validate_output(
    answer: str, max_chars: int, secrets: Iterable[str] = ()
) -> OutputCheck:
    """Valida una respuesta antes de devolverla.

    Una respuesta vacia se cambia por ``EMPTY_ANSWER``; una con un secreto, por
    ``BLOCKED_ANSWER`` (se revisa completa, antes de recortar); el resto se
    recorta a ``max_chars``.

    :param answer: Respuesta del agente
    :type answer: str
    :param max_chars: Largo maximo (``MAX_ANSWER_CHARS``)
    :type max_chars: int
    :param secrets: Valores que nunca deben salir
    :type secrets: collections.abc.Iterable[str]
    :return: Respuesta lista y si se bloqueo
    :rtype: OutputCheck
    """
    if not answer or not answer.strip():
        return OutputCheck(answer=EMPTY_ANSWER)
    if _leaks_secret(answer, secrets):
        return OutputCheck(answer=BLOCKED_ANSWER, blocked=True)
    return OutputCheck(answer=answer[:max_chars])


class RequestGuard:
    """Aplica las guardas a una peticion y deja auditoria y metricas.

    Se crea una por peticion, ligada a su log.

    :param log: Emisor de eventos de la peticion (con ``request_id`` y
        ``client``)
    :type log: app.telemetry.RequestLog
    :param metrics: Metricas del proceso
    :type metrics: app.metrics.Metrics
    :param settings: Configuracion (``pii_policy``, ``max_answer_chars`` y
        ``api_keys``)
    :type settings: app.config.Settings
    """

    def __init__(self, log, metrics, settings):
        self._log = log
        self._metrics = metrics
        self._policy = settings.pii_policy
        self._max_chars = settings.max_answer_chars
        self._secrets = tuple(api_key.key for api_key in settings.api_keys)

    def check_input(self, question: str, history: list) -> GuardedInput:
        """Revisa la pregunta y el historial: inyeccion y datos sensibles.

        :param question: Pregunta tal como llego
        :type question: str
        :param history: Mensajes con ``role`` y ``content``
        :type history: list[dict]
        :return: Pregunta e historial enmascarados y los tipos encontrados
        :rtype: GuardedInput
        :raises InputRejected: Con inyeccion, o con datos sensibles y
            ``PII_POLICY=block``
        """
        self._reject_injection(question, history)
        found = {
            WHERE_QUESTION: pii.detect(question),
            WHERE_HISTORY: sorted(
                {kind for item in history for kind in pii.detect(item["content"])}
            ),
        }
        for where, types in found.items():
            if types:
                self._report_pii(types, where)
        pii_types = tuple(sorted(set(found[WHERE_QUESTION] + found[WHERE_HISTORY])))
        if pii_types and self._policy == PII_POLICY_BLOCK:
            raise InputRejected(SENSITIVE_DATA_DETAIL)
        masked_history = [
            {**item, "content": pii.mask(item["content"])} for item in history
        ]
        return GuardedInput(
            question=pii.mask(question), history=masked_history, pii_types=pii_types
        )

    def check_output(self, answer: str) -> GuardedOutput:
        """Valida la respuesta del agente y enmascara sus datos sensibles.

        :param answer: Respuesta del agente
        :type answer: str
        :return: Respuesta lista, si se bloqueo y los tipos encontrados
        :rtype: GuardedOutput
        """
        # El secreto se busca en la respuesta original, antes de enmascarar.
        check = validate_output(answer, self._max_chars, self._secrets)
        if check.blocked:
            self._log.security_audit(AUDIT_OUTPUT_BLOCKED)
            self._metrics.add_security_event(SECURITY_OUTPUTS_BLOCKED)
            return GuardedOutput(answer=check.answer, blocked=True)
        pii_types = tuple(pii.detect(answer))
        check = validate_output(pii.mask(answer), self._max_chars, self._secrets)
        if pii_types:
            self._report_pii(list(pii_types), WHERE_ANSWER)
        return GuardedOutput(answer=check.answer, pii_types=pii_types)

    def _reject_injection(self, question: str, history: list) -> None:
        """Rechaza la peticion si la pregunta o el historial traen inyeccion.

        :param question: Pregunta tal como llego
        :type question: str
        :param history: Mensajes con ``role`` y ``content``
        :type history: list[dict]
        :raises InputRejected: Si algun texto coincide con un patron
        """
        where = None
        if is_injection(question):
            where = WHERE_QUESTION
        elif any(is_injection(item["content"]) for item in history):
            where = WHERE_HISTORY
        if where is None:
            return
        self._log.security_audit(AUDIT_INPUT_REJECTED, where=where)
        self._metrics.add_security_event(SECURITY_INPUTS_REJECTED)
        raise InputRejected(INPUT_REJECTED_DETAIL)

    def _report_pii(self, types: list, where: str) -> None:
        """Audita y cuenta una deteccion de datos sensibles (solo los tipos).

        :param types: Tipos encontrados, en orden alfabetico
        :type types: list[str]
        :param where: ``question``, ``history`` o ``answer``
        :type where: str
        """
        self._log.security_audit(AUDIT_PII_DETECTED, types=list(types), where=where)
        self._metrics.add_security_event(SECURITY_PII_DETECTIONS)
