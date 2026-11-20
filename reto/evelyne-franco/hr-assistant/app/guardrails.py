"""Controles de seguridad puros: inyeccion, secretos, salida y argumentos.

- ``detect_injection``: busca frases conocidas de inyeccion de
  instrucciones, sin acentos ni mayusculas (``fold_text``). Solo detecta;
  quien llama decide auditar.
- ``redact_secrets``: cambia cada clave de ``API_KEYS`` y el token de
  Cloudflare por ``[REDACTED:secret]``.
- ``validate_answer``: valida la respuesta final del agente (secretos,
  PII, vacia y largo maximo, en ese orden).
- ``validate_tool_args``: minimo privilegio para los argumentos que pide
  el modelo (desde la spec 06 tambien ``search_policy`` y, desde su
  Adenda 1, ``vacation_days``).
- ``screen_answer`` y ``truncate_answer``: las dos mitades de
  ``validate_answer``, para que el revisor compruebe contra los datos
  entre ambas.

Ninguna funcion escribe en el log ni devuelve el valor detectado en un
motivo de rechazo.

:seealso: ``spec/05-security-hardening.md``, puntos 3, 4 y 5.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from app.employee_ids import EMPLOYEE_ID_PATTERN
from app.pii import merge_kinds, redact_pii
from app.text import fold_text

SECRET_MARK = "[REDACTED:secret]"
KIND_SECRET = "secret"
SAFE_FALLBACK_ANSWER = "No pude generar una respuesta segura."
CONTROL_PII = "pii"
CONTROL_SECRET = "secret"
CONTROL_OUTPUT_INVALID = "output_invalid"
CONTROL_TOOL_ARGS = "tool_args"
CONTROL_INJECTION = "injection"
KIND_EMPTY = "empty"
KIND_TOO_LONG = "too_long"
KIND_PHRASE = "phrase"
# Frases de inyeccion ya normalizadas con ``fold_text``.
INJECTION_PHRASES = (
    "ignora las instrucciones",
    "ignora tus instrucciones",
    "ignora todas las instrucciones",
    "ignore previous instructions",
    "ignore all previous instructions",
    "ignore your instructions",
    "olvida tus reglas",
    "olvida las reglas",
    "olvida tus instrucciones",
    "muestra tu prompt",
    "show your prompt",
    "system prompt",
    "actua como",
)
TOOL_GET_EMPLOYEE = "get_employee"
TOOL_SEARCH_BY_DEPARTMENT = "search_by_department"
TOOL_SEARCH_POLICY = "search_policy"
TOOL_VACATION_DAYS = "vacation_days"
EMPLOYEE_ID_PREFIX = "emp-"
MAX_NAME_CHARS = 80
MAX_TOPIC_CHARS = 60


@dataclass(frozen=True)
class AnswerCheck:
    """Resultado de validar la respuesta final.

    :param text: Respuesta lista para devolver.
    :type text: str
    :param kinds: Tipos ocultados (``secret`` y tipos de PII), sin
        repetir; van al campo ``redactions``.
    :type kinds: list[str]
    :param findings: Pares ``(control, tipos)`` para la auditoria.
    :type findings: list[tuple[str, list[str]]]
    """

    text: str
    kinds: list[str] = field(default_factory=list)
    findings: list[tuple[str, list[str]]] = field(default_factory=list)


def _squash(text: str) -> str:
    """Normaliza un texto para buscar frases: sin acentos, mayusculas ni
    espacios repetidos.

    :param text: Texto original.
    :type text: str
    :return: Texto normalizado.
    :rtype: str
    """
    return " ".join(fold_text(text).split())


def detect_injection(text: str) -> bool:
    """Indica si el texto contiene una frase conocida de inyeccion.

    :param text: Pregunta o mensaje del historial.
    :type text: str
    :return: ``True`` si aparece alguna frase de ``INJECTION_PHRASES``.
    :rtype: bool
    """
    squashed = _squash(text)
    return any(phrase in squashed for phrase in INJECTION_PHRASES)


def redact_secrets(text: str, secrets: Iterable[str]) -> tuple[str, bool]:
    """Cambia cada secreto del texto por ``[REDACTED:secret]``.

    Ignora los secretos vacios (si no, ocultarian todo) y reemplaza
    primero los mas largos, para no dejar el resto de uno que contiene a
    otro.

    :param text: Texto a revisar.
    :type text: str
    :param secrets: Claves y tokens conocidos.
    :type secrets: collections.abc.Iterable[str]
    :return: Texto limpio y si se encontro algun secreto.
    :rtype: tuple[str, bool]
    """
    found = False
    for secret in sorted({s for s in secrets if s}, key=len, reverse=True):
        if secret in text:
            found = True
            text = text.replace(secret, SECRET_MARK)
    return text, found


def validate_answer(
    text: str, secrets: Iterable[str], max_chars: int
) -> AnswerCheck:
    """Valida la respuesta final del agente.

    Orden: secretos, PII, respuesta vacia y recorte. Los secretos van
    antes que la PII para que una clave con 10 digitos no salga como
    telefono, y antes del recorte para no dejar parte de una clave.
    Desde la spec 06 es la composicion de ``screen_answer`` y
    ``truncate_answer``; el revisor mete la comprobacion contra los
    datos entre las dos.

    :param text: Respuesta del agente.
    :type text: str
    :param secrets: Claves de ``API_KEYS`` y ``CF_API_TOKEN``.
    :type secrets: collections.abc.Iterable[str]
    :param max_chars: Largo maximo (``MAX_ANSWER_CHARS``).
    :type max_chars: int
    :return: Respuesta valida, tipos ocultados y hallazgos.
    :rtype: AnswerCheck
    """
    screened = screen_answer(text, secrets)
    trimmed, trim_findings = truncate_answer(screened.text, max_chars)
    return AnswerCheck(
        text=trimmed,
        kinds=list(screened.kinds),
        findings=[*screened.findings, *trim_findings],
    )


def screen_answer(text: str, secrets: Iterable[str]) -> AnswerCheck:
    """Primera parte de la validacion: secretos, PII y respuesta vacia.

    :param text: Respuesta del agente.
    :type text: str
    :param secrets: Claves de ``API_KEYS`` y ``CF_API_TOKEN``.
    :type secrets: collections.abc.Iterable[str]
    :return: Respuesta limpia (sin recortar), tipos ocultados y hallazgos.
    :rtype: AnswerCheck
    """
    findings: list[tuple[str, list[str]]] = []
    kinds: list[str] = []
    cleaned, leaked = redact_secrets(text, secrets)
    if leaked:
        kinds.append(KIND_SECRET)
        findings.append((CONTROL_SECRET, [KIND_SECRET]))
    pii = redact_pii(cleaned)
    if pii.kinds:
        kinds = merge_kinds(kinds, pii.kinds)
        findings.append((CONTROL_PII, list(pii.kinds)))
    cleaned = pii.text
    if not cleaned.strip():
        cleaned = SAFE_FALLBACK_ANSWER
        findings.append((CONTROL_OUTPUT_INVALID, [KIND_EMPTY]))
    return AnswerCheck(text=cleaned, kinds=kinds, findings=findings)


def truncate_answer(
    text: str, max_chars: int
) -> tuple[str, list[tuple[str, list[str]]]]:
    """Ultima parte de la validacion: recorta a ``max_chars``.

    :param text: Respuesta ya revisada.
    :type text: str
    :param max_chars: Largo maximo (``MAX_ANSWER_CHARS``).
    :type max_chars: int
    :return: Respuesta recortada y hallazgos (``output_invalid`` con
        ``too_long`` si se recorto).
    :rtype: tuple[str, list[tuple[str, list[str]]]]
    """
    if len(text) > max_chars:
        return text[:max_chars], [(CONTROL_OUTPUT_INVALID, [KIND_TOO_LONG])]
    return text, []


def _has_control_chars(text: str) -> bool:
    """Indica si el texto tiene caracteres de control o invisibles.

    :param text: Texto a revisar.
    :type text: str
    :return: ``True`` si algun caracter es de la categoria Unicode ``C``.
    :rtype: bool
    """
    return any(unicodedata.category(char).startswith("C") for char in text)


def _employee_reason(value: Any) -> str | None:
    """Valida el argumento ``employee_id`` de ``get_employee``.

    Acepta ``EMP-`` seguido de 4 digitos, o un nombre de 1 a 80
    caracteres sin caracteres de control ni PII. Un texto que empieza
    como id (``EMP-``) debe tener la forma exacta.

    :param value: Valor pedido por el modelo.
    :type value: Any
    :return: Motivo del rechazo o ``None`` si es valido.
    :rtype: str | None
    """
    reason = (
        "get_employee acepta un id EMP-#### o un nombre de 1 a "
        f"{MAX_NAME_CHARS} caracteres"
    )
    if not isinstance(value, str):
        return reason
    text = value.strip()
    if EMPLOYEE_ID_PATTERN.fullmatch(text):
        return None
    if fold_text(text).startswith(EMPLOYEE_ID_PREFIX):
        return reason
    if not text or len(value) > MAX_NAME_CHARS or _has_control_chars(value):
        return reason
    if redact_pii(value).kinds:
        return "get_employee no acepta datos personales en el argumento"
    return None


def _department_reason(value: Any, departments: Iterable[str]) -> str | None:
    """Valida el argumento ``department`` de ``search_by_department``.

    :param value: Valor pedido por el modelo.
    :type value: Any
    :param departments: Departamentos que existen en el directorio.
    :type departments: collections.abc.Iterable[str]
    :return: Motivo del rechazo o ``None`` si es valido.
    :rtype: str | None
    """
    if isinstance(value, str):
        wanted = fold_text(value.strip())
        if any(fold_text(dept) == wanted for dept in departments):
            return None
    return "search_by_department acepta solo un departamento del directorio"


def validate_tool_args(
    tool: str, args: Mapping[str, Any], departments: Iterable[str]
) -> str | None:
    """Aplica minimo privilegio a los argumentos de una herramienta.

    :param tool: Herramienta pedida por el modelo.
    :type tool: str
    :param args: Argumentos pedidos por el modelo.
    :type args: collections.abc.Mapping[str, Any]
    :param departments: Departamentos que existen en el directorio.
    :type departments: collections.abc.Iterable[str]
    :return: Motivo del rechazo (sin repetir el valor) o ``None`` si el
        argumento es valido.
    :rtype: str | None
    """
    if tool == TOOL_GET_EMPLOYEE:
        return _employee_reason(args.get("employee_id"))
    if tool == TOOL_SEARCH_BY_DEPARTMENT:
        return _department_reason(args.get("department"), departments)
    if tool == TOOL_SEARCH_POLICY:
        return _topic_reason(args.get("topic"))
    if tool == TOOL_VACATION_DAYS:
        return _vacation_reason(args.get("employee_id"))
    return "herramienta desconocida"


def _vacation_reason(value: Any) -> str | None:
    """Valida el argumento ``employee_id`` de ``vacation_days`` (Adenda 1).

    Solo acepta un id ``EMP-dddd`` exacto, sin nombres.

    :param value: Valor pedido por el modelo.
    :type value: Any
    :return: Motivo del rechazo o ``None`` si es valido.
    :rtype: str | None
    """
    if isinstance(value, str) and EMPLOYEE_ID_PATTERN.fullmatch(value.strip()):
        return None
    return "vacation_days acepta solo un id EMP-####"


def _topic_reason(value: Any) -> str | None:
    """Valida el argumento ``topic`` de ``search_policy`` (spec 06).

    Acepta un texto de 1 a 60 caracteres sin caracteres de control.

    :param value: Valor pedido por el modelo.
    :type value: Any
    :return: Motivo del rechazo o ``None`` si es valido.
    :rtype: str | None
    """
    reason = f"search_policy acepta un tema de 1 a {MAX_TOPIC_CHARS} caracteres"
    if not isinstance(value, str):
        return reason
    if not value.strip() or len(value) > MAX_TOPIC_CHARS:
        return reason
    if _has_control_chars(value):
        return reason
    return None
