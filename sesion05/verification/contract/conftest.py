"""El producto corriendo, para las pruebas de contrato."""

import json
from types import SimpleNamespace

import pytest

from verification.server import running_gateway_product, running_product


@pytest.fixture(scope="session")
def api():
    """El producto con su configuración por omisión."""
    with running_product(8765) as client:
        yield client


@pytest.fixture(scope="session")
def api_one_step():
    """El producto con el bucle limitado a una sola vuelta."""
    with running_product(8766, AGENT_MAX_STEPS="1") as client:
        yield client


@pytest.fixture(scope="session")
def api_limited():
    """El producto con un límite de dos peticiones por minuto."""
    with running_product(8770, RATE_LIMIT_PER_MINUTE="2") as client:
        yield client


@pytest.fixture(scope="session")
def gateway_product(tmp_path_factory):
    """El producto con un modelo real simulado y las peticiones que le llegan.

    ``client`` habla con el producto; ``requests(marker)`` devuelve, en orden,
    los cuerpos que el producto mandó al gateway para la pregunta con ``marker``.
    """
    log = tmp_path_factory.mktemp("gateway") / "requests.jsonl"

    def requests(marker):
        lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
        bodies = [json.loads(line) for line in lines]
        return [
            body for body in bodies
            if marker in [m for m in body["messages"] if m["role"] != "system"][0][
                "content"
            ]
        ]

    with running_gateway_product(8771, log) as client:
        yield SimpleNamespace(client=client, requests=requests)
