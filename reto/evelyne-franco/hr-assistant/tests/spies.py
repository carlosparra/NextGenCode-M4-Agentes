"""Spec 06: dobles espia para el sistema multi-agente.

``SpyModel`` separa las llamadas del supervisor y del especialista;
``TreeTracer`` arma el arbol de runs de cada peticion. ``tests.conftest``
los vuelve a exportar, asi que las pruebas pueden seguir importandolos
desde ahi.
"""

import contextvars
import itertools
import json
import threading

from app.llm import Completion, FakeModel
from tests.sample_data import (
    SAMPLE_EMPLOYEES,
    SUPERVISOR_INPUT_TOKENS,
    SUPERVISOR_OUTPUT_TOKENS,
)


def run_record(name, run_type, metadata, args, kwargs):  # pylint: disable=too-many-arguments,too-many-positional-arguments
    """Arma el registro de una llamada trazada, sin resultado todavia.

    Lo comparten ``TreeTracer`` y ``tests.conftest.RecordingTracer``.

    :param name: Nombre del run.
    :type name: str
    :param run_type: Tipo de corrida (``chain``, ``llm``, ``tool``).
    :type run_type: str
    :param metadata: Metadatos del run.
    :type metadata: dict | None
    :param args: Argumentos posicionales de la llamada.
    :type args: tuple
    :param kwargs: Argumentos con nombre de la llamada.
    :type kwargs: dict
    :return: Registro con ``result`` en ``None``.
    :rtype: dict
    """
    return {
        "name": name,
        "run_type": run_type,
        "metadata": dict(metadata or {}),
        "args": args,
        "kwargs": kwargs,
        "result": None,
    }


def _is_supervisor_call(messages):
    """Indica si los mensajes son la llamada de clasificacion del supervisor.

    El supervisor manda primero un mensaje ``system`` con
    ``app.prompts.SUPERVISOR_PROMPT``.

    :param messages: Mensajes de la llamada.
    :type messages: list[dict[str, str]]
    :return: ``True`` si es la llamada del supervisor.
    :rtype: bool
    """
    # Importacion perezosa: el modulo es nuevo en la spec 06.
    from app.prompts import SUPERVISOR_PROMPT  # pylint: disable=import-outside-toplevel

    return bool(messages) and messages[0].get("content") == SUPERVISOR_PROMPT


class SpyModel:
    """Modelo espia que separa las llamadas del supervisor y del especialista.

    - Al supervisor le responde ``supervisor_reply`` (texto crudo) con
      ``SUPERVISOR_INPUT_TOKENS`` y ``SUPERVISOR_OUTPUT_TOKENS``; si es
      ``None``, delega en ``FakeModel``.
    - Al especialista le responde, en orden, cada decision de
      ``replies`` (la ultima se repite) con 1 token de entrada y 1 de
      salida; si ``replies`` esta vacio, delega en ``FakeModel``.

    :param name: Nombre del modelo (debe tener precio).
    :type name: str
    :param supervisor_reply: Texto que contesta como supervisor.
    :type supervisor_reply: str | None
    :param replies: Decisiones JSON del especialista, por ejemplo
        ``{"answer": "..."}`` o ``{"tool": "...", "args": {...}}``.
    :type replies: list[dict] | None
    """

    def __init__(self, name="fake", supervisor_reply=None, replies=None):
        """Guarda las respuestas y prepara las listas de llamadas.

        :param name: Nombre del modelo.
        :type name: str
        :param supervisor_reply: Texto que contesta como supervisor.
        :type supervisor_reply: str | None
        :param replies: Decisiones JSON del especialista.
        :type replies: list[dict] | None
        """
        self.name = name
        self.supervisor_reply = supervisor_reply
        self.replies = list(replies or [])
        self.supervisor_calls = []
        self.specialist_calls = []
        self._inner = FakeModel(
            name=name, departments=[e["department"] for e in SAMPLE_EMPLOYEES]
        )
        self._lock = threading.Lock()

    def complete(self, messages):
        """Anota la llamada y responde segun el papel.

        :param messages: Mensajes de la conversacion.
        :type messages: list[dict[str, str]]
        :return: Respuesta del papel correspondiente.
        :rtype: app.llm.Completion
        """
        copy = [dict(m) for m in messages]
        if _is_supervisor_call(messages):
            with self._lock:
                self.supervisor_calls.append(copy)
            if self.supervisor_reply is None:
                return self._inner.complete(messages)
            return Completion(
                text=self.supervisor_reply,
                input_tokens=SUPERVISOR_INPUT_TOKENS,
                output_tokens=SUPERVISOR_OUTPUT_TOKENS,
                cached=False,
            )
        with self._lock:
            self.specialist_calls.append(copy)
            index = min(len(self.specialist_calls), len(self.replies)) - 1
        if not self.replies:
            return self._inner.complete(messages)
        raw = json.dumps(self.replies[index], ensure_ascii=False)
        return Completion(text=raw, input_tokens=1, output_tokens=1, cached=False)

    def specialist_text(self):
        """Devuelve todo lo que recibio el especialista como texto.

        :return: Contenido de todos los mensajes del especialista.
        :rtype: str
        """
        return " ".join(
            str(m.get("content", "")) for call in self.specialist_calls for m in call
        )


class TreeTracer:
    """Trazador espia que arma el arbol de runs de cada peticion.

    Cada run se anota al **empezar** con su ``id``, su padre
    (``parent``, ``None`` si es raiz), nombre, tipo, metadatos,
    argumentos y, al terminar, su resultado. La pila de runs abiertos
    vive en un ``contextvars.ContextVar``, asi que es segura con hilos y
    sigue el mismo anidamiento que LangSmith. ``annotate`` agrega
    metadatos al run abierto mas reciente.
    """

    enabled = True

    def __init__(self):
        """Inicializa la lista de runs, la pila y el contador de ids."""
        self.runs = []
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._stack = contextvars.ContextVar("tree_tracer_stack", default=())

    def traceable(self, name, run_type, metadata=None):
        """Crea un decorador que anota cada llamada como un run del arbol.

        :param name: Nombre del run.
        :type name: str
        :param run_type: Tipo de corrida (``chain``, ``llm``, ``tool``).
        :type run_type: str
        :param metadata: Metadatos del run.
        :type metadata: dict | None
        :return: Decorador que anota y delega.
        :rtype: callable
        """

        def decorator(func):
            def wrapper(*args, **kwargs):
                stack = self._stack.get()
                run = run_record(name, run_type, metadata, args, kwargs)
                run["parent"] = stack[-1]["id"] if stack else None
                with self._lock:
                    run["id"] = next(self._ids)
                    self.runs.append(run)
                token = self._stack.set((*stack, run))
                try:
                    run["result"] = func(*args, **kwargs)
                finally:
                    self._stack.reset(token)
                return run["result"]

            return wrapper

        return decorator

    def annotate(self, metadata):
        """Agrega metadatos al run abierto mas reciente.

        :param metadata: Metadatos a agregar.
        :type metadata: dict
        """
        stack = self._stack.get()
        if stack:
            stack[-1]["metadata"].update(metadata)

    def roots(self):
        """Devuelve los runs sin padre.

        :return: Runs raiz, en orden de inicio.
        :rtype: list[dict]
        """
        return [run for run in self.runs if run["parent"] is None]

    def children(self, run):
        """Devuelve los hijos directos de un run, en orden de inicio.

        :param run: Run padre.
        :type run: dict
        :return: Hijos directos.
        :rtype: list[dict]
        """
        return [r for r in self.runs if r["parent"] == run["id"]]

    def descendants(self, run):
        """Devuelve todos los runs que quedan dentro de un run.

        :param run: Run de arriba.
        :type run: dict
        :return: Hijos, nietos y demas, en orden de inicio.
        :rtype: list[dict]
        """
        found = []
        for child in self.children(run):
            found.append(child)
            found.extend(self.descendants(child))
        return found

    def child_named(self, run, name):
        """Devuelve el unico hijo directo de ``run`` con un nombre.

        :param run: Run padre.
        :type run: dict
        :param name: Nombre buscado, por ejemplo ``agent.guard``.
        :type name: str
        :return: El hijo encontrado.
        :rtype: dict
        """
        matches = [c for c in self.children(run) if c["name"] == name]
        assert len(matches) == 1, [c["name"] for c in self.children(run)]
        return matches[0]
