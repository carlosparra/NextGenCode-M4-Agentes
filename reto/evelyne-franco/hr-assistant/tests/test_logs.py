"""Pruebas unitarias del log JSON.

Cada evento es una linea JSON con ``ts`` (ISO 8601 en UTC),
``service``, ``event`` y ``request_id``. La hora sale de un reloj
falso, asi que la prueba es determinista.
"""

import io
import json
from datetime import datetime

from app.logs import JsonLogger
from tests.conftest import FIXED_NOW, FakeClock


def _logger(stream):
    """Crea un logger sobre ``stream`` con el reloj falso.

    :param stream: Destino del log.
    :type stream: io.StringIO
    :return: Logger listo para usar.
    :rtype: app.logs.JsonLogger
    """
    return JsonLogger(stream=stream, service="hr-assistant", clock=FakeClock())


def test_each_event_is_one_json_line_with_required_fields():
    """Dos eventos producen dos lineas con los campos obligatorios."""
    stream = io.StringIO()
    logger = _logger(stream)

    logger.emit("request", "req-1", method="GET", status=200)
    logger.emit("agent_run", "req-1", steps=2)

    lines = stream.getvalue().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["event"] == "request"
    assert first["service"] == "hr-assistant"
    assert first["request_id"] == "req-1"
    assert first["method"] == "GET"
    assert first["status"] == 200
    ts = datetime.fromisoformat(first["ts"].replace("Z", "+00:00"))
    assert ts == FIXED_NOW
    assert ts.utcoffset().total_seconds() == 0


def test_non_ascii_and_newlines_stay_on_one_line():
    """Acentos y saltos de linea en un valor no rompen la linea."""
    stream = io.StringIO()
    logger = _logger(stream)

    logger.emit("audit", "req-2", args={"department": "Tecnología\nX"})

    lines = stream.getvalue().splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["args"] == {"department": "Tecnología\nX"}
