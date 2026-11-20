"""Interfaz del modelo de lenguaje, modelo simulado y fabrica de modelos.

El agente solo conoce el protocolo ``LLM``: ``complete(messages)`` devuelve una
``Completion`` con el texto del modelo, los tokens de entrada y salida, el
nombre del modelo y si vino de la cache.
"""

import json
import re

from app.completion import LLM, Completion
from app.config import PROVIDER_FAKE, PROVIDER_GATEWAY, ConfigError, Settings
from app.directory import EmployeeDirectory, normalize_text
from app.gateway import GatewayLLM, build_http_client

__all__ = ["LLM", "Completion", "FakeLLM", "build_llm", "build_models"]

TOOL_RESULT_PREFIX = "Resultado de la herramienta: "
HELP_MESSAGE = "Pregúntame por un empleado (EMP-0001) o un departamento."
EMPLOYEE_ID_PATTERN = re.compile(r"\bEMP-\d{4}\b", re.IGNORECASE)
FAKE_MODEL_NAME = "fake"


def count_words(text: str) -> int:
    """Cuenta palabras separadas por espacios.

    :param text: Texto a contar
    :type text: str
    :return: Numero de palabras
    :rtype: int
    """
    return len(str(text).split())


class FakeLLM:  # pylint: disable=too-few-public-methods
    """Modelo simulado: determinista, sin red ni costo.

    Decide con reglas sobre el ultimo mensaje, en este orden de prioridad:
    resultado de herramienta, id de empleado, departamento y mensaje de ayuda.
    Responde igual con cualquier nombre; el nombre solo decide el precio.

    :param departments: Departamentos existentes en los datos
    :type departments: list[str]
    :param model: Nombre con el que firma sus respuestas
    :type model: str
    """

    def __init__(self, departments, model: str = FAKE_MODEL_NAME):
        self._departments = tuple(
            (name, normalize_text(name)) for name in departments if name
        )
        self._model = model

    def complete(self, messages: list) -> Completion:
        """Responde segun las reglas del modelo simulado.

        :param messages: Mensajes con ``role`` y ``content``
        :type messages: list[dict]
        :return: Un objeto JSON serializado, los tokens contados por palabras
            y el nombre del modelo
        :rtype: Completion
        """
        last = str(messages[-1].get("content", "")) if messages else ""
        text = json.dumps(self._decide(last), ensure_ascii=False)
        input_tokens = sum(
            count_words(message.get("content", "")) for message in messages
        )
        return Completion(
            text=text,
            input_tokens=input_tokens,
            output_tokens=count_words(text),
            model=self._model,
        )

    def _decide(self, last: str) -> dict:
        """Aplica las cuatro reglas al ultimo mensaje.

        :param last: Contenido del ultimo mensaje
        :type last: str
        :return: Peticion de herramienta o respuesta final
        :rtype: dict
        """
        if last.startswith(TOOL_RESULT_PREFIX):
            result = last[len(TOOL_RESULT_PREFIX):]
            return {"answer": f"Según el directorio: {result}"}
        match = EMPLOYEE_ID_PATTERN.search(last)
        if match:
            employee_id = match.group(0).upper()
            return {"tool": "get_employee", "args": {"employee_id": employee_id}}
        department = self._find_department(last)
        if department:
            return {
                "tool": "search_by_department",
                "args": {"department": department},
            }
        return {"answer": HELP_MESSAGE}

    def _find_department(self, text: str):
        """Busca en el texto un departamento existente.

        :param text: Texto donde buscar
        :type text: str
        :return: Nombre del departamento o ``None`` si no menciona ninguno
        :rtype: str or None
        """
        normalized = normalize_text(text)
        for name, key in self._departments:
            if re.search(rf"\b{re.escape(key)}\b", normalized):
                return name
        return None


def _build_model(settings: Settings, model: str, departments, http_client) -> LLM:
    """Construye un modelo con nombre segun ``MODEL_PROVIDER``.

    :param settings: Configuracion de la aplicacion
    :type settings: Settings
    :param model: Nombre del modelo
    :type model: str
    :param departments: Departamentos existentes (para el modelo simulado)
    :type departments: list[str]
    :param http_client: Cliente HTTP para el gateway; ``None`` crea uno
    :type http_client: httpx.Client or None
    :return: Implementacion del protocolo ``LLM``
    :rtype: LLM
    :raises ConfigError: Si el proveedor no esta soportado
    """
    if settings.model_provider == PROVIDER_FAKE:
        return FakeLLM(departments, model=model)
    if settings.model_provider == PROVIDER_GATEWAY:
        client = http_client if http_client is not None else build_http_client()
        return GatewayLLM(settings, model, client)
    raise ConfigError(
        f"MODEL_PROVIDER not supported: {settings.model_provider!r}"
    )


def build_llm(settings: Settings, directory: EmployeeDirectory) -> LLM:
    """Construye un solo modelo indicado por ``MODEL_PROVIDER``.

    Se conserva de la sesion 1: el simulado firma como ``fake`` (precio 0) y
    el de gateway usa ``MODEL_SMALL``.

    :param settings: Configuracion de la aplicacion
    :type settings: Settings
    :param directory: Directorio de empleados (para conocer los departamentos)
    :type directory: EmployeeDirectory
    :return: Implementacion del protocolo ``LLM``
    :rtype: LLM
    :raises ConfigError: Si el proveedor no esta soportado
    """
    model = settings.model_small
    if settings.model_provider == PROVIDER_FAKE:
        model = FAKE_MODEL_NAME
    return _build_model(settings, model, directory.departments(), None)


def build_models(
    settings: Settings, directory: EmployeeDirectory, http_client=None
) -> dict:
    """Construye un modelo por nombre: ``MODEL_SMALL`` y ``MODEL_LARGE``.

    Con ``fake`` son dos modelos simulados que responden igual pero cuestan
    segun su nombre; con ``gateway`` comparten el cliente HTTP.

    :param settings: Configuracion de la aplicacion
    :type settings: Settings
    :param directory: Directorio de empleados (para conocer los departamentos)
    :type directory: EmployeeDirectory
    :param http_client: Cliente HTTP para el gateway; ``None`` crea uno
    :type http_client: httpx.Client or None
    :return: Modelo por nombre
    :rtype: dict[str, LLM]
    :raises ConfigError: Si el proveedor no esta soportado
    """
    departments = directory.departments()
    if settings.model_provider == PROVIDER_GATEWAY and http_client is None:
        http_client = build_http_client()
    return {
        name: _build_model(settings, name, departments, http_client)
        for name in (settings.model_small, settings.model_large)
    }
