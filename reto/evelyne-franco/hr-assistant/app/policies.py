"""Politicas de Recursos Humanos para el especialista ``policy``.

``PolicyBook`` carga ``data/policies.json`` (una lista de politicas con
``topic``, ``keywords`` y ``text``) y expone:

- ``search_policy(topic)``: la herramienta de solo lectura del
  especialista. Busca sin acentos ni mayusculas por ``topic`` o por
  cualquiera de sus ``keywords``.
- ``match_question(text)``: el tema cuya palabra clave aparece en una
  pregunta, con limites de palabra. Si hay varias, gana la palabra clave
  mas larga y luego el orden del archivo. La usa el supervisor.

:seealso: ``spec/06-multiagente.md``, punto 2.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.text import fold_text

TOPIC_NOT_FOUND = "tema no encontrado"


@dataclass(frozen=True)
class Policy:
    """Una politica de Recursos Humanos.

    :param topic: Tema de la politica, por ejemplo ``vacaciones``.
    :type topic: str
    :param keywords: Palabras clave que la identifican.
    :type keywords: tuple[str, ...]
    :param text: Texto completo de la politica.
    :type text: str
    """

    topic: str
    keywords: tuple[str, ...]
    text: str

    def names(self) -> tuple[str, ...]:
        """Devuelve el tema y las palabras clave ya normalizados.

        :return: Nombres sin acentos ni mayusculas, sin repetir.
        :rtype: tuple[str, ...]
        """
        folded = [fold_text(self.topic), *(fold_text(k) for k in self.keywords)]
        return tuple(dict.fromkeys(name.strip() for name in folded if name.strip()))


def _contains_phrase(folded_text: str, phrase: str) -> bool:
    """Indica si una frase aparece completa (con limites de palabra).

    :param folded_text: Texto ya normalizado con ``fold_text``.
    :type folded_text: str
    :param phrase: Frase ya normalizada.
    :type phrase: str
    :return: ``True`` si la frase aparece sin letras pegadas.
    :rtype: bool
    """
    pattern = r"(?<!\w)" + re.escape(phrase) + r"(?!\w)"
    return re.search(pattern, folded_text) is not None


class PolicyBook:
    """Libro de politicas cargado en memoria (solo lectura).

    :param policies: Politicas en el orden del archivo.
    :type policies: collections.abc.Iterable[Policy]
    """

    def __init__(self, policies: Iterable[Policy]) -> None:
        """Guarda las politicas.

        :param policies: Politicas en el orden del archivo.
        :type policies: collections.abc.Iterable[Policy]
        """
        self._policies = tuple(policies)

    @classmethod
    def from_file(cls, path: str) -> PolicyBook:
        """Carga y valida el archivo de politicas.

        :param path: Ruta al JSON de politicas.
        :type path: str
        :return: Libro de politicas.
        :rtype: PolicyBook
        :raises FileNotFoundError: Si el archivo no existe.
        :raises ValueError: Si el contenido no tiene la forma esperada.
        """
        with open(path, encoding="utf-8") as file:
            data = json.load(file)
        return cls.from_data(data, path)

    @classmethod
    def from_data(cls, data: Any, source: str = "policies") -> PolicyBook:
        """Construye el libro a partir de datos ya leidos.

        :param data: Lista de politicas con ``topic``, ``keywords`` y
            ``text``.
        :type data: Any
        :param source: Nombre del origen, para el mensaje de error.
        :type source: str
        :return: Libro de politicas.
        :rtype: PolicyBook
        :raises ValueError: Si el contenido no tiene la forma esperada.
        """
        if not isinstance(data, list):
            raise ValueError(f"Se esperaba una lista de politicas en {source}")
        policies = []
        for item in data:
            if not isinstance(item, dict):
                raise ValueError(f"Cada politica de {source} debe ser un objeto")
            topic, keywords, text = (
                item.get("topic"),
                item.get("keywords", []),
                item.get("text"),
            )
            if not isinstance(topic, str) or not isinstance(text, str):
                raise ValueError(f"Politica sin topic o text en {source}")
            if not isinstance(keywords, list) or not all(
                isinstance(k, str) for k in keywords
            ):
                raise ValueError(f"keywords debe ser una lista de textos en {source}")
            policies.append(Policy(topic=topic, keywords=tuple(keywords), text=text))
        return cls(policies)

    @property
    def topics(self) -> list[str]:
        """Temas disponibles, en el orden del archivo.

        :return: Lista de temas.
        :rtype: list[str]
        """
        return [policy.topic for policy in self._policies]

    def keyword_topics(self) -> dict[str, str]:
        """Devuelve cada nombre normalizado con su tema.

        Incluye el tema y las palabras clave; el primero que aparece en
        el archivo gana si se repite.

        :return: Palabra clave normalizada -> tema.
        :rtype: dict[str, str]
        """
        mapping: dict[str, str] = {}
        for policy in self._policies:
            for name in policy.names():
                mapping.setdefault(name, policy.topic)
        return mapping

    def find(self, topic: str) -> Policy | None:
        """Busca una politica por tema o palabra clave, sin acentos.

        :param topic: Tema o palabra clave buscada.
        :type topic: str
        :return: La politica encontrada o ``None``.
        :rtype: Policy | None
        """
        wanted = " ".join(fold_text(topic).split())
        for policy in self._policies:
            if wanted in policy.names():
                return policy
        return None

    def search_policy(self, topic: str) -> dict[str, Any]:
        """Herramienta ``search_policy`` del especialista ``policy``.

        :param topic: Tema o palabra clave (ya validado).
        :type topic: str
        :return: ``{"topic", "text"}`` si existe; si no,
            ``{"error": "tema no encontrado", "topics": [...]}``.
        :rtype: dict[str, Any]
        """
        policy = self.find(topic)
        if policy is None:
            return {"error": TOPIC_NOT_FOUND, "topics": self.topics}
        return {"topic": policy.topic, "text": policy.text}

    def match_question(self, text: str) -> str | None:
        """Devuelve el tema cuya palabra clave aparece en la pregunta.

        Compara sin acentos ni mayusculas y con limites de palabra. Si
        varias aparecen, gana la mas larga y luego el orden del archivo
        (``prima de vacaciones`` gana a ``vacaciones``).

        :param text: Pregunta ya limpia.
        :type text: str
        :return: Tema encontrado o ``None``.
        :rtype: str | None
        """
        folded = " ".join(fold_text(text).split())
        best_topic: str | None = None
        best_length = 0
        for policy in self._policies:
            for name in policy.names():
                if len(name) > best_length and _contains_phrase(folded, name):
                    best_topic, best_length = policy.topic, len(name)
        return best_topic
