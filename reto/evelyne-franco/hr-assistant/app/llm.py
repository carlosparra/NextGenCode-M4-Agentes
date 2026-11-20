"""Modelos del HR Assistant: simulado y fabrica por nombre.

Reexporta la interfaz ``Model``, ``Completion`` y ``ModelUnavailable``
de ``app.completion``, implementa el modelo simulado (fake) con conteo
aproximado de tokens y ``build_models``, que crea un modelo por cada
nombre configurado (``MODEL_SMALL`` y ``MODEL_LARGE``).

:seealso: ADR 0002 sobre la abstraccion del modelo y
    ``spec/03-costs.md``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping

import httpx

from app.completion import (
    TOOL_RESULT_PREFIX,
    Completion,
    Model,
    ModelUnavailable,
)
from app.config import PROVIDER_FAKE, PROVIDER_GATEWAY, Settings
from app.directory import Directory
from app.gateway import GATEWAY_TIMEOUT_SECONDS, GatewayModel
from app.policies import PolicyBook
from app.prompts import POLICY_PROMPT, SUPERVISOR_PROMPT
from app.text import fold_text
from app.vacations import is_vacation_result, vacation_sentence

__all__ = [
    "Completion",
    "FakeModel",
    "Model",
    "ModelUnavailable",
    "TOOL_RESULT_PREFIX",
    "build_models",
]

# Departamentos de respaldo si no se inyectan los de los datos.
DEFAULT_DEPARTMENTS = (
    "Tecnología",
    "Ventas",
    "Finanzas",
)
HELP_MESSAGE = "Pregúntame por un empleado (EMP-0001) o un departamento."
POLICY_HELP_MESSAGE = (
    "Pregúntame por una política de Recursos Humanos, por ejemplo "
    "vacaciones, aguinaldo u home office."
)
FAKE_MODEL_NAME = "fake"
# Spec 06: palabras clave de respaldo (copia de ``spec/policies.json``)
# si no se inyectan las de ``PolicyBook``; palabra clave -> tema.
DEFAULT_POLICY_KEYWORDS = {
    "vacaciones": "vacaciones",
    "dias libres": "vacaciones",
    "descanso anual": "vacaciones",
    "prima vacacional": "prima vacacional",
    "prima de vacaciones": "prima vacacional",
    "aguinaldo": "aguinaldo",
    "home office": "home office",
    "trabajo remoto": "home office",
    "teletrabajo": "home office",
    "trabajo desde casa": "home office",
    "permiso": "permisos",
    "permisos": "permisos",
    "paternidad": "permisos",
    "maternidad": "permisos",
    "horario": "horario",
    "jornada": "horario",
    "hora de entrada": "horario",
    "hora de salida": "horario",
}
SYSTEM_ROLE = "system"
SPECIALIST_DIRECTORY = "directory"
SPECIALIST_POLICY = "policy"


def build_models(
    settings: Settings,
    directory: Directory,
    client: httpx.Client | None = None,
    policies: PolicyBook | None = None,
) -> dict[str, Model]:
    """Crea un modelo por cada nombre configurado.

    Con ``MODEL_PROVIDER=fake`` son dos modelos simulados que responden
    igual pero se llaman como ``MODEL_SMALL`` y ``MODEL_LARGE`` (asi
    tienen precio). Con ``gateway`` son clientes de AI Gateway que
    comparten un ``httpx.Client``.

    :param settings: Configuracion validada.
    :type settings: app.config.Settings
    :param directory: Directorio, del que salen los departamentos.
    :type directory: app.directory.Directory
    :param client: Cliente HTTP para el gateway; si falta, se crea uno
        con el tiempo maximo por llamada.
    :type client: httpx.Client | None
    :param policies: Politicas, de las que salen las palabras clave del
        modelo simulado (spec 06); si falta, se usan las de respaldo.
    :type policies: app.policies.PolicyBook | None
    :return: Modelos por nombre.
    :rtype: dict[str, app.completion.Model]
    :raises ValueError: Si el proveedor no es soportado.
    """
    names = (settings.model_small, settings.model_large)
    if settings.model_provider == PROVIDER_FAKE:
        keywords = policies.keyword_topics() if policies is not None else None
        return {
            name: FakeModel(
                name=name,
                departments=directory.departments,
                policy_keywords=keywords,
            )
            for name in names
        }
    if settings.model_provider == PROVIDER_GATEWAY:
        shared = client or httpx.Client(timeout=GATEWAY_TIMEOUT_SECONDS)
        return {
            name: GatewayModel(name=name, settings=settings, client=shared)
            for name in names
        }
    raise ValueError(
        f"Proveedor de modelo no soportado: {settings.model_provider}"
    )


class FakeModel(Model):
    """Modelo simulado determinista, sin red ni costo.

    Decide con reglas sobre el ultimo mensaje del usuario:

    1. Si empieza con ``Resultado de la herramienta: ``
       responde con ``answer``.
    2. Si contiene un id ``EMP-XXXX`` pide ``get_employee``.
    3. Si menciona un departamento conocido pide
       ``search_by_department``.
    4. Si no, responde con un mensaje de ayuda.

    Desde la spec 06 reconoce su papel por el primer mensaje ``system``:

    - Con ``SUPERVISOR_PROMPT`` responde ``{"specialist": "policy"}`` si
      el ultimo mensaje trae una palabra clave de politica y
      ``{"specialist": "directory"}`` si no.
    - Con ``POLICY_PROMPT`` responde el texto de un resultado de
      herramienta si lo recibio; si no, pide ``search_policy`` con el
      tema de la palabra clave del ultimo mensaje o responde con ayuda.
      Desde la Adenda 1, si recibio un resultado de ``vacation_days``
      responde la frase armada con ese resultado.
    - Sin ``system`` (especialista ``directory``) aplica las reglas de
      siempre.

    :seealso: ``spec/01-architecture.md`` seccion modelo simulado y
        ``spec/06-multiagente.md`` punto 3.

    :param name: Nombre del modelo, con el que se busca su precio.
    :type name: str
    :param departments: Departamentos que existen en los datos; si
        falta, se usa ``DEFAULT_DEPARTMENTS``.
    :type departments: collections.abc.Iterable[str] | None
    :param policy_keywords: Palabra clave -> tema de cada politica; si
        falta, se usa ``DEFAULT_POLICY_KEYWORDS``.
    :type policy_keywords: collections.abc.Mapping[str, str] | None
    """

    def __init__(
        self,
        name: str = FAKE_MODEL_NAME,
        departments: Iterable[str] | None = None,
        policy_keywords: Mapping[str, str] | None = None,
    ) -> None:
        """Guarda el nombre, los departamentos y las palabras clave.

        :param name: Nombre del modelo.
        :type name: str
        :param departments: Departamentos de los datos.
        :type departments: collections.abc.Iterable[str] | None
        :param policy_keywords: Palabra clave -> tema.
        :type policy_keywords: collections.abc.Mapping[str, str] | None
        """
        self.name = name
        known = DEFAULT_DEPARTMENTS if departments is None else departments
        self._departments = sorted(set(known))
        keywords = (
            DEFAULT_POLICY_KEYWORDS if policy_keywords is None else policy_keywords
        )
        # Las mas largas primero: ``prima de vacaciones`` gana a ``vacaciones``.
        self._policy_keywords = sorted(
            ((fold_text(k), topic) for k, topic in keywords.items()),
            key=lambda pair: len(pair[0]),
            reverse=True,
        )

    def complete(self, messages: list[dict[str, str]]) -> Completion:
        """Aplica las reglas del modelo simulado.

        No guarda estado: los tokens viajan en el ``Completion``.

        :param messages: Lista de mensajes de la conversacion.
        :type messages: list[dict[str, str]]
        :return: Decision del modelo en JSON y sus tokens.
        :rtype: app.completion.Completion
        """
        role = self._role(messages)
        last = self._last_user_content(messages)
        if role == SUPERVISOR_PROMPT:
            response = self._classify(last)
        elif role == POLICY_PROMPT:
            response = self._decide_policy(messages, last)
        else:
            response = self._decide(last)
        return Completion(
            text=response,
            input_tokens=self._count_words(messages),
            output_tokens=len(response.split()),
            cached=False,
        )

    # -- Metodos internos -----------------------------------------------

    @staticmethod
    def _role(messages: list[dict[str, str]]) -> str | None:
        """Devuelve el prompt de sistema del primer mensaje, si lo hay.

        :param messages: Lista de mensajes.
        :type messages: list[dict[str, str]]
        :return: Contenido del ``system`` inicial o ``None``.
        :rtype: str | None
        """
        if messages and messages[0].get("role") == SYSTEM_ROLE:
            return messages[0].get("content", "")
        return None

    def _policy_topic(self, text: str) -> str | None:
        """Busca el tema de la palabra clave de politica mas larga del texto.

        :param text: Texto del ultimo mensaje.
        :type text: str
        :return: Tema o ``None``.
        :rtype: str | None
        """
        folded = fold_text(text)
        for keyword, topic in self._policy_keywords:
            if re.search(r"(?<!\w)" + re.escape(keyword) + r"(?!\w)", folded):
                return topic
        return None

    def _classify(self, text: str) -> str:
        """Papel de supervisor: elige el especialista.

        :param text: Texto del ultimo mensaje del usuario.
        :type text: str
        :return: ``{"specialist": "policy"}`` o ``{"specialist": "directory"}``.
        :rtype: str
        """
        topic = self._policy_topic(text)
        specialist = SPECIALIST_DIRECTORY if topic is None else SPECIALIST_POLICY
        return json.dumps({"specialist": specialist})

    def _decide_policy(self, messages: list[dict[str, str]], text: str) -> str:
        """Papel de especialista ``policy``.

        :param messages: Lista de mensajes.
        :type messages: list[dict[str, str]]
        :param text: Texto del ultimo mensaje del usuario.
        :type text: str
        :return: Cadena JSON con la decision.
        :rtype: str
        """
        results = [
            m.get("content", "")
            for m in messages
            if m.get("role") == "user"
            and m.get("content", "").startswith(TOOL_RESULT_PREFIX)
        ]
        if results:
            return json.dumps(
                {"answer": self._policy_answer(results)}, ensure_ascii=False
            )
        topic = self._policy_topic(text)
        if topic is not None:
            return json.dumps(
                {"tool": "search_policy", "args": {"topic": topic}},
                ensure_ascii=False,
            )
        return json.dumps({"answer": POLICY_HELP_MESSAGE}, ensure_ascii=False)

    @staticmethod
    def _policy_answer(results: list[str]) -> str:
        """Arma la respuesta de ``policy`` con los resultados recibidos.

        Adenda 1: con un resultado valido de ``vacation_days`` responde la
        frase armada en codigo (A5); si no, el texto de la ultima politica
        recibida; si no, el mensaje de ayuda.

        :param results: Mensajes con ``TOOL_RESULT_PREFIX``, en orden.
        :type results: list[str]
        :return: Texto de la respuesta.
        :rtype: str
        """
        parsed = []
        for raw in results:
            try:
                parsed.append(json.loads(raw[len(TOOL_RESULT_PREFIX):]))
            except json.JSONDecodeError:
                continue
        vacations = [data for data in parsed if is_vacation_result(data)]
        if vacations:
            return vacation_sentence(vacations[-1])
        texts = [
            data["text"]
            for data in parsed
            if isinstance(data, dict) and isinstance(data.get("text"), str)
        ]
        return texts[-1] if texts else POLICY_HELP_MESSAGE

    def _last_user_content(
        self, messages: list[dict[str, str]]
    ) -> str:
        """Obtiene el contenido del ultimo mensaje del usuario.

        :param messages: Lista de mensajes.
        :type messages: list[dict[str, str]]
        :return: Contenido del ultimo mensaje de rol 'user'.
        :rtype: str
        """
        for msg in reversed(messages):
            if msg.get("role") == "user":
                return msg.get("content", "")
        return ""

    def _decide(self, text: str) -> str:
        """Aplica las reglas en orden de prioridad.

        :param text: Texto del ultimo mensaje del usuario.
        :type text: str
        :return: Cadena JSON con la decision.
        :rtype: str
        """
        # Regla 1: resultado de herramienta
        if text.startswith(TOOL_RESULT_PREFIX):
            result_data = text[len(TOOL_RESULT_PREFIX):]
            return json.dumps(
                {"answer": f"Según el directorio: {result_data}"},
                ensure_ascii=False,
            )

        # Regla 2: id de empleado
        match = re.search(r"EMP-\d{4}", text)
        if match:
            return json.dumps(
                {
                    "tool": "get_employee",
                    "args": {"employee_id": match.group()},
                }
            )

        # Regla 3: departamento que existe en los datos (sin acentos)
        folded = fold_text(text)
        for dept in self._departments:
            if fold_text(dept) in folded:
                return json.dumps(
                    {
                        "tool": "search_by_department",
                        "args": {"department": dept},
                    },
                    ensure_ascii=False,
                )

        # Regla 4: mensaje de ayuda
        return json.dumps({"answer": HELP_MESSAGE}, ensure_ascii=False)

    def _count_words(
        self, messages: list[dict[str, str]]
    ) -> int:
        """Cuenta palabras en todos los mensajes (tokens aprox).

        :param messages: Lista de mensajes.
        :type messages: list[dict[str, str]]
        :return: Numero total de palabras.
        :rtype: int
        """
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            total += len(content.split())
        return total
