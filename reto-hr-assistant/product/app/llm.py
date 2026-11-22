"""Interfaz del modelo de lenguaje y modelo simulado determinista."""

import json
import re
from typing import Protocol

from app.gateway import GatewayModel, default_http_client
from app.model_reply import ModelReply

__all__ = [
    "FakeModel",
    "LanguageModel",
    "ModelReply",
    "build_model",
    "build_models",
]

TOOL_RESULT_PREFIX = "Resultado de la herramienta: "
HELP_ANSWER = "Pregúntame por un empleado (EMP-0001) o un departamento."
EMPLOYEE_ID_PATTERN = re.compile(r"EMP-\d{4}")
VACATION_KEYWORD = "vacaciones"
SUMMARY_KEYWORD = "resumen"


class LanguageModel(Protocol):
    """Interfaz que debe cumplir cualquier modelo usado por el agente."""

    def complete(self, messages: list[dict]) -> ModelReply:
        """Genera la siguiente respuesta de la conversación.

        :param messages: Mensajes con ``role`` y ``content``
        :type messages: list[dict]
        :return: Respuesta del modelo
        :rtype: ModelReply
        """


def _count_words(text: str) -> int:
    """Cuenta palabras separadas por espacios.

    :param text: Texto a contar
    :type text: str
    :return: Número de palabras
    :rtype: int
    """
    return len(str(text).split())


class FakeModel:
    """Modelo simulado: decide con reglas fijas sobre el último mensaje.

    :param departments: Departamentos que existen en los datos
    :type departments: list[str]
    """

    def __init__(self, departments):
        self._departments = tuple(departments)

    def _mentioned_department(self, lowered: str) -> str | None:
        """Busca el primer departamento conocido que aparece en el texto.

        :param lowered: Texto ya pasado a minúsculas con ``casefold``
        :type lowered: str
        :return: Nombre del departamento o ``None`` si no aparece ninguno
        :rtype: str or None
        """
        for department in self._departments:
            if department.casefold() in lowered:
                return department
        return None

    def _decide(self, last: str) -> dict:
        """Aplica las reglas en orden de prioridad.

        Las reglas de vacaciones y de resumen van antes que las de
        ``get_employee`` y ``search_by_department``, porque sus preguntas
        también traen un id o un departamento.

        :param last: Contenido del último mensaje
        :type last: str
        :return: Objeto del protocolo (herramienta o respuesta)
        :rtype: dict
        """
        if last.startswith(TOOL_RESULT_PREFIX):
            result = last[len(TOOL_RESULT_PREFIX) :]
            return {"answer": f"Según el directorio: {result}"}
        lowered = last.casefold()
        match = EMPLOYEE_ID_PATTERN.search(last)
        if match and VACATION_KEYWORD in lowered:
            return {
                "tool": "get_vacation_balance",
                "args": {"employee_id": match.group(0)},
            }
        department = self._mentioned_department(lowered)
        if department is not None and SUMMARY_KEYWORD in lowered:
            return {"tool": "department_summary", "args": {"department": department}}
        if match:
            return {"tool": "get_employee", "args": {"employee_id": match.group(0)}}
        if department is not None:
            return {
                "tool": "search_by_department",
                "args": {"department": department},
            }
        return {"answer": HELP_ANSWER}

    def complete(self, messages: list[dict]) -> ModelReply:
        """Genera una respuesta JSON del protocolo.

        :param messages: Mensajes con ``role`` y ``content``
        :type messages: list[dict]
        :return: Respuesta con conteo aproximado de tokens
        :rtype: ModelReply
        """
        last = str(messages[-1].get("content", "")) if messages else ""
        text = json.dumps(self._decide(last), ensure_ascii=False)
        input_tokens = sum(
            _count_words(message.get("content", "")) for message in messages
        )
        return ModelReply(
            text=text,
            input_tokens=input_tokens,
            output_tokens=_count_words(text),
        )


def build_models(settings, directory, http_client=None) -> dict:
    """Construye los modelos ``MODEL_SMALL`` y ``MODEL_LARGE`` del proveedor.

    Con ``fake`` son dos modelos simulados que responden igual y solo cambian de
    nombre (y de precio); no se crea ningún cliente HTTP. Con ``gateway`` ambos
    comparten el cliente HTTP, que se puede inyectar para no tocar la red.

    :param settings: Configuración validada
    :type settings: app.config.Settings
    :param directory: Directorio de empleados
    :type directory: app.directory.EmployeeDirectory
    :param http_client: Cliente HTTP para el gateway; si falta se crea uno real
    :type http_client: httpx.Client or None
    :return: Modelo por nombre
    :rtype: dict[str, LanguageModel]
    :raises ValueError: Si el proveedor no está soportado
    """
    names = (settings.costs.model_small, settings.costs.model_large)
    if settings.model_provider == "fake":
        return {name: FakeModel(directory.departments()) for name in names}
    if settings.model_provider == "gateway":
        client = http_client if http_client is not None else default_http_client()
        return {name: GatewayModel(name, settings.gateway, client) for name in names}
    raise ValueError(f"Unsupported model provider: {settings.model_provider}")


def build_model(settings, directory) -> LanguageModel:
    """Construye un único modelo indicado por ``MODEL_PROVIDER``.

    Se conserva por compatibilidad: con ``gateway`` devuelve ``MODEL_LARGE``.

    :param settings: Configuración validada
    :type settings: app.config.Settings
    :param directory: Directorio de empleados
    :type directory: app.directory.EmployeeDirectory
    :return: Modelo listo para usarse
    :rtype: LanguageModel
    :raises ValueError: Si el proveedor no está soportado
    """
    if settings.model_provider == "fake":
        return FakeModel(directory.departments())
    return build_models(settings, directory)[settings.costs.model_large]
