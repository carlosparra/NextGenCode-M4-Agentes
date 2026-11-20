"""Pruebas unitarias de las trazas opcionales con LangSmith.

Se reemplaza el paquete ``langsmith`` por un modulo falso, asi que
ninguna prueba toca la red.
"""

import os
import sys
import types

import pytest

from app.config import load_settings
from app.tracing import Tracer, TracingOptions, traceable


@pytest.fixture()
def fake_langsmith(monkeypatch):
    """Instala un ``langsmith`` falso que anota cada uso de traceable.

    :param monkeypatch: Utilidad de pytest para parchar.
    :type monkeypatch: pytest.MonkeyPatch
    :return: Lista donde se anotan los argumentos de cada uso.
    :rtype: list[dict]
    """
    calls = []

    def traceable(*args, **kwargs):
        calls.append(kwargs)

        def decorator(func):
            return func

        if args and callable(args[0]):
            return decorator(args[0])
        return decorator

    module = types.ModuleType("langsmith")
    module.traceable = traceable
    monkeypatch.setitem(sys.modules, "langsmith", module)
    for name in (
        "LANGSMITH_API_KEY",
        "LANGSMITH_TRACING",
        "HIDE_INPUTS",
        "HIDE_OUTPUTS",
        "LANGSMITH_HIDE_INPUTS",
        "LANGSMITH_HIDE_OUTPUTS",
    ):
        # setenv antes de delenv: asi pytest restaura el entorno al final,
        # aunque el codigo bajo prueba escriba estas variables.
        monkeypatch.setenv(name, "placeholder")
        monkeypatch.delenv(name)
    return calls


def _double(value):
    """Funcion de ejemplo para decorar.

    :param value: Numero de entrada.
    :type value: int
    :return: El doble de ``value``.
    :rtype: int
    """
    return value * 2


def test_tracing_does_nothing_without_api_key(fake_langsmith, monkeypatch):
    """Con trazas encendidas pero sin clave, no se usa LangSmith."""
    monkeypatch.setenv("LANGSMITH_TRACING", "true")

    decorated = traceable(name="lookup", run_type="tool")(_double)

    assert decorated(2) == 4
    assert not fake_langsmith


def test_tracing_wraps_with_langsmith_and_hides_inputs(
    fake_langsmith, monkeypatch
):
    """Con trazas y clave, se envuelve con LangSmith y se ocultan
    entradas y salidas por omision.
    """
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")

    decorated = traceable(name="lookup", run_type="tool")(_double)

    assert decorated(2) == 4
    assert any(
        call.get("name") == "lookup" and call.get("run_type") == "tool"
        for call in fake_langsmith
    )
    assert os.environ.get("LANGSMITH_HIDE_INPUTS") == "true"
    assert os.environ.get("LANGSMITH_HIDE_OUTPUTS") == "true"


def _tracer_for(env):
    """Construye un trazador con las mismas reglas que ``Settings``.

    :param env: Entorno inyectado; el trazador escribe en el.
    :type env: dict[str, str]
    :return: Trazador configurado con ``load_settings(env)``.
    :rtype: app.tracing.Tracer
    """
    options = TracingOptions.from_settings(load_settings(env))
    return Tracer(options, environ=env)


def test_tracing_value_one_turns_tracing_on_like_settings(fake_langsmith):
    """``LANGSMITH_TRACING=1`` es verdadero en Settings y enciende las trazas."""
    env = {"LANGSMITH_TRACING": "1", "LANGSMITH_API_KEY": "test-key"}

    tracer = _tracer_for(env)
    decorated = tracer.traceable(name="lookup", run_type="tool")(_double)

    assert load_settings(env).langsmith_tracing is True
    assert tracer.enabled is True
    assert decorated(2) == 4
    assert any(call.get("name") == "lookup" for call in fake_langsmith)


@pytest.mark.usefixtures("fake_langsmith")
def test_hide_inputs_zero_sends_inputs_like_settings():
    """``HIDE_INPUTS=0`` es falso en Settings y deja de ocultar entradas,
    sin tocar ``os.environ`` del proceso.
    """
    env = {
        "LANGSMITH_TRACING": "yes",
        "LANGSMITH_API_KEY": "test-key",
        "HIDE_INPUTS": "0",
    }

    _tracer_for(env)

    assert load_settings(env).hide_inputs is False
    assert env["LANGSMITH_HIDE_INPUTS"] == "false"
    assert env["LANGSMITH_HIDE_OUTPUTS"] == "true"
    assert "LANGSMITH_HIDE_INPUTS" not in os.environ


def test_annotate_does_not_import_langsmith_when_tracing_is_off(monkeypatch):
    """Spec 06: con trazas apagadas, ``annotate`` no hace nada ni importa."""
    monkeypatch.delitem(sys.modules, "langsmith", raising=False)
    tracer = Tracer(TracingOptions(enabled=False), environ={})

    tracer.annotate({"specialist": "policy", "supervisor_route": "rule:policy"})

    assert "langsmith" not in sys.modules
