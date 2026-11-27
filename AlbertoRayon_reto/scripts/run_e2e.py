"""Arranca el producto con el modelo simulado y corre las pruebas de Playwright.

Uso: ``python scripts/run_e2e.py``. La clave de prueba se toma de ``E2E_API_KEY``
o se genera para esta corrida; nunca va escrita en las pruebas.
"""

import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
PORT = 8791


def main() -> int:
    """Corre las pruebas e2e y devuelve su código de salida."""
    key = os.environ.get("E2E_API_KEY") or secrets.token_urlsafe(24)
    env = {**os.environ, "MODEL_PROVIDER": "fake", "ENVIRONMENT": "development",
           "API_KEYS": f"e2e:{key}", "RATE_LIMIT_PER_MINUTE": "1000",
           "E2E_API_KEY": key}
    url = f"http://127.0.0.1:{PORT}"
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT),
         "--log-level", "warning"],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL,
    )
    try:
        for _ in range(60):
            try:
                httpx.get(f"{url}/health", timeout=1)
                break
            except httpx.TransportError:
                time.sleep(0.25)
        command = [sys.executable, "-m", "pytest", "e2e", "-q", "-p",
                   "no:cacheprovider", "--base-url", url]
        return subprocess.run(command, cwd=ROOT, env=env, check=False).returncode
    finally:
        server.terminate()
        server.wait(timeout=10)


if __name__ == "__main__":
    sys.exit(main())
