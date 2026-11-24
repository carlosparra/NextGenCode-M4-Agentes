"""Arranca el producto con el modelo simulado para las pruebas de navegador."""

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
PORT = 8799
# Clave de prueba: solo existe en esta corrida, no es un secreto
E2E_KEY = os.environ.get("E2E_API_KEY", "e2e-key-0123456789abcdef")


@pytest.fixture(scope="session")
def base_url():
    env = {
        **os.environ,
        "MODEL_PROVIDER": "fake",
        "ENVIRONMENT": "development",
        "API_KEYS": f"e2e:{E2E_KEY}",
        "RATE_LIMIT_PER_MINUTE": "1000",
        "LANGSMITH_TRACING": "false",
    }
    command = [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT)]
    server = subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{PORT}"
    try:
        for _ in range(60):
            try:
                httpx.get(f"{url}/health", timeout=1)
                break
            except httpx.TransportError:
                time.sleep(0.25)
        yield url
    finally:
        server.terminate()
        server.wait(timeout=10)


@pytest.fixture
def key():
    return E2E_KEY
