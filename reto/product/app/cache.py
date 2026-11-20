"""Palanca 5: cache de respuestas en memoria de este proceso.

Una pregunta repetida (misma pregunta normalizada, mismo modelo elegido y
misma ventana de historial) se responde sin llamar al modelo. La cache es una
LRU de ``RESPONSE_CACHE_SIZE`` entradas con TTL de
``RESPONSE_CACHE_TTL_SECONDS``; lleva su propio reloj inyectado y un
``threading.Lock`` porque FastAPI atiende ``POST /ask`` en su pool de hilos.
Es estado por proceso: con varios workers cada uno tiene la suya (ADR 0015 y
0016).

Nunca se guarda una respuesta si la pregunta o el historial tenian datos
sensibles, ni una salida bloqueada: ``is_storable`` es una defensa en
profundidad, conservadora, que no depende de las guardas de ``app.pii`` y
``app.guardrails``.
"""

import hashlib
import json
import re
import threading
from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass

from app.clock import Clock

CACHE_HIT = "hit"
CACHE_MISS = "miss"

_WHITESPACE = re.compile(r"\s+")
# Patrones amplios a proposito: un falso positivo solo cuesta un ``miss``.
_SENSITIVE_INPUT_PATTERNS = (
    # Correo electronico.
    re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+"),
    # Telefono, tarjeta o NSS: 10 o mas digitos con separadores opcionales.
    re.compile(r"(?:\d[\s.\-]?){10,}"),
    # CURP o RFC: 3 o 4 letras, fecha de 6 digitos y homoclave.
    re.compile(r"\b[A-Z&Ñ]{3,4}\d{6}[A-Z0-9]{2,8}\b", re.IGNORECASE),
)
_SECRET_OUTPUT_PATTERNS = (
    re.compile(r"\bBearer\s+\S+", re.IGNORECASE),
    re.compile(r"\b[0-9a-fA-F]{32,}\b"),
)


@dataclass(frozen=True)
class CachedAnswer:
    """Lo que se guarda de una respuesta: sin tokens ni costo.

    :param answer: Respuesta final ya validada
    :type answer: str
    :param steps: Vueltas del bucle del agente
    :type steps: int
    :param tools_used: Herramientas usadas, en orden
    :type tools_used: tuple[str, ...]
    :param model: Modelo que la produjo
    :type model: str or None
    """

    answer: str
    steps: int
    tools_used: tuple
    model: str | None = None


def normalize_question(question: str) -> str:
    """Normaliza una pregunta para la clave: sin mayusculas ni espacios extra.

    :param question: Pregunta tal como llego
    :type question: str
    :return: Pregunta en minusculas con los espacios colapsados
    :rtype: str
    """
    return _WHITESPACE.sub(" ", question).strip().casefold()


def cache_key(question: str, model: str, history: list) -> str:
    """Calcula la clave de una pregunta.

    La clave es un SHA-256: el texto de la pregunta no queda en memoria como
    clave legible.

    :param question: Pregunta del cliente
    :type question: str
    :param model: Modelo elegido por el enrutador
    :type model: str
    :param history: Ventana de historial que se manda al modelo (ya recortada)
    :type history: list[dict]
    :return: Clave hexadecimal
    :rtype: str
    """
    window = [
        [str(message.get("role", "")), str(message.get("content", ""))]
        for message in history
    ]
    material = json.dumps(
        [normalize_question(question), model, window], ensure_ascii=False
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _has_sensitive_data(text: str) -> bool:
    """Indica si un texto parece contener datos sensibles.

    :param text: Pregunta o mensaje del historial
    :type text: str
    :return: ``True`` si algun patron coincide
    :rtype: bool
    """
    return any(pattern.search(text) for pattern in _SENSITIVE_INPUT_PATTERNS)


def _leaks_secret(answer: str, secrets: Iterable[str]) -> bool:
    """Indica si una respuesta parece llevar un secreto.

    :param answer: Respuesta del agente
    :type answer: str
    :param secrets: Valores que nunca deben salir (las claves de ``API_KEYS``)
    :type secrets: collections.abc.Iterable[str]
    :return: ``True`` si trae un secreto o un patron de secreto
    :rtype: bool
    """
    if any(secret and secret in answer for secret in secrets):
        return True
    return any(pattern.search(answer) for pattern in _SECRET_OUTPUT_PATTERNS)


def is_storable(
    inputs: Iterable[str], answer: str, secrets: Iterable[str] = ()
) -> bool:
    """Decide si una respuesta se puede guardar en la cache.

    :param inputs: Pregunta y mensajes del historial tal como llegaron
    :type inputs: collections.abc.Iterable[str]
    :param answer: Respuesta que se devolveria
    :type answer: str
    :param secrets: Valores que nunca deben salir
    :type secrets: collections.abc.Iterable[str]
    :return: ``False`` si hay datos sensibles en la entrada o un secreto en
        la salida
    :rtype: bool
    """
    if any(_has_sensitive_data(text) for text in inputs):
        return False
    return not _leaks_secret(answer, secrets)


class ResponseCache:
    """Cache LRU en memoria con TTL, reloj inyectado y candado.

    :param max_entries: Entradas maximas; al pasarse se desaloja la menos
        usada recientemente
    :type max_entries: int
    :param ttl_seconds: Segundos que vive una entrada
    :type ttl_seconds: float
    :param clock: Reloj con ``monotonic()``; el TTL se mide con el
    :type clock: app.clock.Clock
    :raises ValueError: Si ``max_entries`` o ``ttl_seconds`` no son positivos
    """

    def __init__(self, max_entries: int, ttl_seconds: float, clock: Clock):
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be > 0")
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._entries = OrderedDict()

    def get(self, key: str):
        """Devuelve el valor guardado si existe y no vencio.

        Un acierto mueve la entrada al final (la mas reciente); una entrada
        vencida se borra.

        :param key: Clave de ``cache_key``
        :type key: str
        :return: El valor guardado o ``None``
        :rtype: object or None
        """
        now = self._clock.monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if now >= expires_at:
                del self._entries[key]
                return None
            self._entries.move_to_end(key)
            return value

    def put(self, key: str, value) -> None:
        """Guarda un valor y desaloja la entrada menos usada si no cabe.

        :param key: Clave de ``cache_key``
        :type key: str
        :param value: Valor a guardar
        :type value: object
        """
        expires_at = self._clock.monotonic() + self._ttl_seconds
        with self._lock:
            self._entries[key] = (expires_at, value)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def __len__(self) -> int:
        """Cuenta las entradas guardadas (incluye las vencidas sin leer).

        :return: Numero de entradas
        :rtype: int
        """
        with self._lock:
            return len(self._entries)
