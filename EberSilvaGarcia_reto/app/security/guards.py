"""Validación de entradas y salidas de los agentes.

- Entradas: caracteres de control, inyección de instrucciones y preguntas
  que piden datos personales protegidos.
- Salidas: PII, fuga del prompt de sistema y largo máximo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.directory import normalize
from app.security import pii

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_INJECTION = tuple(
    re.compile(pattern)
    for pattern in (
        r"ignora (todas )?(las|tus) (instrucciones|reglas)",
        r"olvida (todas )?(las|tus) (instrucciones|reglas)",
        r"ignore (all |the )?(previous|prior|above) instructions",
        r"(muestra|revela|dime|imprime) (tu|el) (prompt|mensaje) (de )?sistema",
        r"system prompt",
        r"actua como (si fueras )?(el )?administrador",
        r"modo desarrollador|developer mode|jailbreak",
    )
)
_TOPICS = (
    r"curp|rfc|nss|seguro social|salario|sueldo|telefono|celular|correo( personal)?"
    r"|email|domicilio|direccion|cuenta bancaria|clabe"
)
# Se considera solicitud cuando se PIDE el dato: "cuál es el CURP de...",
# "dame el salario...", "el teléfono de EMP-0004", "cuánto gana...".
_PROTECTED_REQUEST = tuple(
    re.compile(pattern)
    for pattern in (
        rf"\b(cual|dame|dime|muestra|muestrame|pasa|pasame|necesito|quiero|consulta"
        rf"|obten|busca|envia|comparte)\b.*\b({_TOPICS})\b",
        rf"\b({_TOPICS})\b\s+(de|del)\b",
        r"\bcuanto gana\b",
    )
)
SYSTEM_MARKER = "HRA-SYSTEM-PROMPT"
MAX_OUTPUT_CHARS = 4000


class GuardRejection(ValueError):
    """Una entrada que la política no deja pasar.

    :param reason: Código corto del motivo (para auditoría y métricas)
    :type reason: str
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class CheckedInput:
    """Pregunta ya revisada, lista para el agente."""

    text: str
    pii_kinds: tuple[str, ...]
    asks_protected_data: bool


def check_input(text: str, pii_policy: str = "mask") -> CheckedInput:
    """Revisa la pregunta de una persona antes de que llegue al modelo.

    :param text: Pregunta original
    :type text: str
    :param pii_policy: ``mask`` enmascara la PII; ``block`` rechaza la pregunta
    :type pii_policy: str
    :return: Pregunta limpia y lo que se encontró
    :rtype: CheckedInput
    :raises GuardRejection: Si hay inyección de instrucciones, o PII con ``block``
    """
    cleaned = _CONTROL.sub("", text).strip()
    if not cleaned:
        raise GuardRejection("empty", "question is empty")
    flat = normalize(cleaned)
    if any(pattern.search(flat) for pattern in _INJECTION):
        raise GuardRejection("prompt_injection", "question rejected by security policy")
    found = pii.scan(cleaned)
    if found.found and pii_policy == "block":
        raise GuardRejection("pii", "question contains personal data")
    asks = any(pattern.search(flat) for pattern in _PROTECTED_REQUEST)
    return CheckedInput(found.text, found.kinds, asks)


@dataclass(frozen=True)
class CheckedOutput:
    """Respuesta revisada antes de devolverla."""

    text: str
    pii_kinds: tuple[str, ...]
    leaked_prompt: bool


def check_output(text: str) -> CheckedOutput:
    """Revisa la respuesta del modelo antes de entregarla.

    :param text: Respuesta del modelo
    :type text: str
    :return: Respuesta segura y lo que se corrigió
    :rtype: CheckedOutput
    """
    leaked = SYSTEM_MARKER in text
    if leaked:
        text = "No puedo compartir esa información."
    found = pii.scan(text, include_amounts=True)
    safe = found.text[:MAX_OUTPUT_CHARS]
    return CheckedOutput(safe, found.kinds, leaked)
