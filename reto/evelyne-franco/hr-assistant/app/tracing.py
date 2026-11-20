"""Trazas opcionales con LangSmith.

Las decisiones de trazado salen de ``app.config.Settings``
(``langsmith_tracing``, ``hide_inputs`` y ``hide_outputs``), con las
mismas reglas de conversion que el resto de la configuracion. Solo la
existencia de ``LANGSMITH_API_KEY`` se lee del entorno; la clave nunca
se guarda ni se registra.

``Tracer`` envuelve una funcion con ``langsmith.traceable`` solo si las
trazas estan encendidas y existe la clave. Si no, devuelve la funcion
sin cambios: no importa ``langsmith`` ni intenta conectarse.

:seealso: ``spec/02-observability.md``, punto 4, y ADR 0006.
"""

from __future__ import annotations

import importlib
import os
from collections.abc import Callable, MutableMapping
from dataclasses import dataclass
from typing import Any, TypeVar

from app.config import Settings, load_settings

FuncT = TypeVar("FuncT", bound=Callable[..., Any])

API_KEY_VARIABLE = "LANGSMITH_API_KEY"
HIDE_INPUTS_VARIABLE = "LANGSMITH_HIDE_INPUTS"
HIDE_OUTPUTS_VARIABLE = "LANGSMITH_HIDE_OUTPUTS"


def _as_text(value: bool) -> str:
    """Convierte un booleano al texto que espera LangSmith.

    :param value: Valor a convertir.
    :type value: bool
    :return: ``true`` o ``false``.
    :rtype: str
    """
    return "true" if value else "false"


@dataclass(frozen=True)
class TracingOptions:
    """Opciones de trazado tomadas de la configuracion.

    Por omision las trazas estan apagadas y, si se encienden, se
    ocultan entradas y salidas (valor seguro).

    :param enabled: Enciende las trazas en LangSmith.
    :type enabled: bool
    :param hide_inputs: No mandar entradas a LangSmith.
    :type hide_inputs: bool
    :param hide_outputs: No mandar salidas a LangSmith.
    :type hide_outputs: bool
    """

    enabled: bool = False
    hide_inputs: bool = True
    hide_outputs: bool = True

    @classmethod
    def from_settings(cls, settings: Settings) -> TracingOptions:
        """Construye las opciones a partir de la configuracion validada.

        :param settings: Configuracion de la aplicacion.
        :type settings: app.config.Settings
        :return: Opciones de trazado.
        :rtype: TracingOptions
        """
        return cls(
            enabled=settings.langsmith_tracing,
            hide_inputs=settings.hide_inputs,
            hide_outputs=settings.hide_outputs,
        )


class Tracer:
    """Crea decoradores que trazan funciones en LangSmith si aplica.

    Si las trazas estan encendidas y hay clave, al construirse fija
    ``LANGSMITH_HIDE_INPUTS`` y ``LANGSMITH_HIDE_OUTPUTS`` en el entorno
    inyectado segun las opciones, porque LangSmith las lee de ahi.

    :param options: Opciones de trazado.
    :type options: TracingOptions
    :param environ: Entorno donde se busca la clave y se fijan las
        variables de LangSmith; por omision ``os.environ``.
    :type environ: collections.abc.MutableMapping[str, str] | None
    """

    def __init__(
        self,
        options: TracingOptions,
        environ: MutableMapping[str, str] | None = None,
    ) -> None:
        """Inicializa el trazador con sus opciones y su entorno.

        :param options: Opciones de trazado.
        :type options: TracingOptions
        :param environ: Entorno; por omision ``os.environ``.
        :type environ: collections.abc.MutableMapping[str, str] | None
        """
        self._options = options
        self._environ = os.environ if environ is None else environ
        if self.enabled:
            self._environ[HIDE_INPUTS_VARIABLE] = _as_text(options.hide_inputs)
            self._environ[HIDE_OUTPUTS_VARIABLE] = _as_text(options.hide_outputs)

    @property
    def enabled(self) -> bool:
        """Indica si las trazas estan encendidas y hay clave.

        :return: ``True`` si se debe trazar con LangSmith.
        :rtype: bool
        """
        return self._options.enabled and bool(self._environ.get(API_KEY_VARIABLE))

    def traceable(
        self,
        name: str,
        run_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> Callable[[FuncT], FuncT]:
        """Crea un decorador que traza la funcion en LangSmith si aplica.

        :param name: Nombre de la traza.
        :type name: str
        :param run_type: Tipo de corrida (``chain``, ``llm``, ``tool``).
        :type run_type: str
        :param metadata: Metadatos de la traza, por ejemplo ``request_id``.
        :type metadata: dict[str, Any] | None
        :return: Decorador; identidad si las trazas estan apagadas.
        :rtype: collections.abc.Callable
        """
        if not self.enabled:
            return lambda func: func
        # Importacion perezosa: sin trazas, langsmith ni siquiera se carga.
        langsmith = importlib.import_module("langsmith")
        return langsmith.traceable(
            name=name, run_type=run_type, metadata=dict(metadata or {})
        )

    def annotate(self, metadata: dict[str, Any]) -> None:
        """Agrega metadatos al run abierto mas reciente (spec 06).

        Sirve para el run raiz ``request``: abre antes de que el
        supervisor decida, y despues se le agregan ``specialist`` y
        ``supervisor_route``. Con las trazas apagadas no hace nada ni
        importa ``langsmith``. Nunca debe recibir texto ni la clave.

        :param metadata: Metadatos a agregar, por ejemplo
            ``{"specialist": "policy"}``.
        :type metadata: dict[str, Any]
        """
        if not self.enabled:
            return
        # Importacion perezosa: solo con trazas encendidas.
        run_helpers = importlib.import_module("langsmith.run_helpers")
        run_tree = run_helpers.get_current_run_tree()
        if run_tree is not None:
            run_tree.add_metadata(dict(metadata))


def tracer_from_environ(environ: MutableMapping[str, str] | None = None) -> Tracer:
    """Construye un trazador leyendo la configuracion con ``load_settings``.

    Usa las mismas reglas que ``app.config`` (``1``/``yes``/``true`` y
    ``0``/``no``/``false``), asi que nunca contradice a ``Settings``.

    :param environ: Variables de entorno; por omision ``os.environ``.
    :type environ: collections.abc.MutableMapping[str, str] | None
    :return: Trazador configurado.
    :rtype: Tracer
    :raises ValueError: Si algun valor de configuracion es invalido.
    """
    env = os.environ if environ is None else environ
    options = TracingOptions.from_settings(load_settings(env))
    return Tracer(options, env)


def traceable(
    name: str,
    run_type: str,
    metadata: dict[str, Any] | None = None,
    environ: MutableMapping[str, str] | None = None,
) -> Callable[[FuncT], FuncT]:
    """Atajo que crea un decorador con la configuracion del entorno.

    Equivale a ``tracer_from_environ(environ).traceable(...)``. La
    aplicacion no lo usa: ``create_app`` inyecta un ``Tracer`` construido
    con ``Settings``.

    :param name: Nombre de la traza.
    :type name: str
    :param run_type: Tipo de corrida (``chain``, ``llm``, ``tool``).
    :type run_type: str
    :param metadata: Metadatos de la traza, por ejemplo ``request_id``.
    :type metadata: dict[str, Any] | None
    :param environ: Variables de entorno; por omision ``os.environ``.
    :type environ: collections.abc.MutableMapping[str, str] | None
    :return: Decorador; identidad si las trazas estan apagadas.
    :rtype: collections.abc.Callable
    """
    return tracer_from_environ(environ).traceable(name, run_type, metadata)
