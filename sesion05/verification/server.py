"""Arranca el producto con el modelo simulado para probarlo por HTTP.

Las verificaciones no importan el código del producto: le hablan como un
cliente, así que valen sin importar cómo lo haya escrito el agente.
"""

import os
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import httpx

PRODUCT = Path(__file__).resolve().parent.parent / "product"
HARNESS = Path(__file__).resolve().parent / "gateway_harness.py"
# Clave de prueba de la fábrica: no es un secreto, solo existe en estas corridas
FACTORY_KEY = "factory-key-0123456789"
DEFAULTS = {
    "MODEL_PROVIDER": "fake",
    "API_KEYS": f"factory:{FACTORY_KEY}",
    "RATE_LIMIT_PER_MINUTE": "1000",
}


@contextmanager
def running_product(port: int, command: list[str] | None = None, **env: str):
    """Corre ``uvicorn app.main:app`` en ``port`` mientras dure el bloque.

    El cliente que entrega ya manda la clave de la fábrica en ``X-API-Key``.
    ``command`` reemplaza el comando de arranque (lo usa el gateway simulado).
    """
    settings = {**os.environ, **DEFAULTS, **env}
    command = command or [
        sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)
    ]
    server = subprocess.Popen(command, cwd=PRODUCT, env=settings)
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(40):
            try:
                httpx.get(f"{url}/health", timeout=1)
                break
            except httpx.TransportError:
                time.sleep(0.25)
        yield httpx.Client(
            base_url=url, timeout=10, headers={"X-API-Key": FACTORY_KEY}
        )
    finally:
        server.terminate()
        server.wait(timeout=10)


@contextmanager
def running_gateway_product(port: int, log: Path, **env: str):
    """Corre el producto con ``MODEL_PROVIDER=gateway`` y Cloudflare simulado.

    El simulado vive dentro del proceso del producto (``gateway_harness.py``) y
    guarda cada petición que recibe en ``log``, una línea JSON por petición.
    """
    settings = {
        "MODEL_PROVIDER": "gateway",
        "CF_ACCOUNT_ID": "factory-acc",
        "CF_GATEWAY_ID": "factory-gw",
        "CF_API_TOKEN": "factory-token",
        "FACTORY_GATEWAY_LOG": str(log),
        **env,
    }
    command = [sys.executable, str(HARNESS), str(port)]
    with running_product(port, command=command, **settings) as client:
        yield client
