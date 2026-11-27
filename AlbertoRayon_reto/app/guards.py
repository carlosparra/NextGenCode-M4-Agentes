"""Guardas de entrada y de salida alrededor de los agentes."""

import re
from dataclasses import dataclass, field

from app import pii
from app.directory import normalize

# Marcador que vive en el prompt de sistema: si aparece en una respuesta, se filtró
CANARY = "HR-CANARY-7f3a"
LEAK_ANSWER = "No puedo compartir esa información."
INJECTION = re.compile(
    r"ignor[ae]\w* (?:todas? )?(?:las |tus |the |all |your )?(?:instrucciones|"
    r"reglas|previous|instructions)|olvida (?:todas? )?(?:las |tus )?(?:instrucciones"
    r"|reglas)|system prompt|prompt de(?:l)? sistema|(?:revela|muestra|repite|dime)"
    r" (?:tu|tus|el) (?:prompt|instrucciones)|jailbreak|modo desarrollador|"
    r"developer mode|actua como (?:si|un|una) |you are now",
)
PROTECTED = (
    r"curp|rfc|nss|seguro social|domicilio|direccion|telefono|celular|correo|email|"
    r"salario|sueldo|cuenta bancaria|clabe|tarjeta"
)
# Pedir el dato de otra persona: verbo de solicitud, dato protegido y un tercero
PROTECTED_REQUEST = re.compile(
    rf"(?:dame|dime|muestra|pasame|necesito|quiero|cual es|cuales son|consulta|"
    rf"busca|comparte|envia)\b.{{0,40}}\b(?:{PROTECTED})\b.{{0,20}}\b(?:de|del)\b"
)


class GuardBlocked(Exception):
    """La petición no puede pasar al modelo."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class GuardedText:
    """Texto que ya pasó una guarda."""

    text: str
    pii_types: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


def check_input(text: str) -> GuardedText:
    """Revisa una pregunta antes de que llegue al modelo.

    :param text: Pregunta o mensaje del historial
    :type text: str
    :return: El texto con los datos personales enmascarados
    :rtype: GuardedText
    :raises GuardBlocked: Con ``prompt_injection`` o ``protected_data_request``
    """
    plain = normalize(text)
    if INJECTION.search(plain):
        raise GuardBlocked("prompt_injection")
    if PROTECTED_REQUEST.search(plain):
        raise GuardBlocked("protected_data_request")
    masked, found = pii.mask(text)
    return GuardedText(masked, found)


def check_output(text: str, max_chars: int) -> GuardedText:
    """Revisa una respuesta antes de entregarla.

    :param text: Respuesta del agente
    :type text: str
    :param max_chars: Largo máximo permitido
    :type max_chars: int
    :return: La respuesta sin datos personales, sin el prompt de sistema y recortada
    :rtype: GuardedText
    """
    if CANARY in text:
        return GuardedText(LEAK_ANSWER, flags=["system_prompt_leak"])
    masked, found = pii.mask(text)
    flags = ["pii_in_output"] if found else []
    if len(masked) > max_chars:
        masked = masked[:max_chars].rstrip() + "..."
        flags.append("truncated")
    return GuardedText(masked, found, flags)
