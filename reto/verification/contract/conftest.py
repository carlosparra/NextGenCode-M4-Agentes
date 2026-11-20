"""El producto corriendo, para las pruebas de contrato."""

import pytest

from verification.server import running_product


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
def api_block_pii():
    """El producto que rechaza preguntas con datos sensibles."""
    with running_product(8773, PII_POLICY="block") as client:
        yield client


@pytest.fixture(scope="session")
def api_cached():
    """El producto con la caché de respuestas encendida."""
    with running_product(8774, RESPONSE_CACHE_TTL_SECONDS="300") as client:
        yield client
