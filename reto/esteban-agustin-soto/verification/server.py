"""Arranca el producto con el modelo simulado para probarlo por HTTP.

Las verificaciones no importan el código del producto: le hablan como un
cliente, así que valen sin importar cómo lo haya escrito el agente.
"""

import os
import subprocess
import sys
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path

import httpx

PRODUCT = Path(__file__).resolve().parent.parent / "product"
# Clave de prueba de la fábrica: no es un secreto, solo existe en estas corridas
FACTORY_KEY = "factory-key-0123456789"
# Arranca el producto confiando en los certificados del sistema, si se puede
SYSTEM_CERTS_BOOT = """
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass
import uvicorn
uvicorn.run("app.main:app", port={port})
"""
DEFAULTS = {
    "MODEL_PROVIDER": "fake",
    "API_KEYS": f"factory:{FACTORY_KEY}",
    "RATE_LIMIT_PER_MINUTE": "1000",
}


@contextmanager
def running_product(
    port: int, log_path: Path | None = None, timeout: float = 10,
    system_certs: bool = False, **env: str,
):
    """Corre ``uvicorn app.main:app`` en ``port`` mientras dure el bloque.

    El cliente que entrega ya manda la clave de la fábrica en ``X-API-Key``.
    Con ``log_path`` toda la salida del producto (el log JSON y el de uvicorn)
    se guarda en ese archivo, para que una prueba pueda leerla.
    ``timeout`` es el tiempo máximo de cada petición del cliente que entrega.
    Con ``system_certs`` el producto confía en los certificados del sistema
    operativo (``truststore``), para redes que interceptan TLS.

    :param port: Puerto local donde escucha el producto
    :type port: int
    :param log_path: Archivo donde se guarda la salida del producto; ``None``
        la deja en la consola
    :type log_path: pathlib.Path or None
    :param timeout: Segundos máximos de cada petición del cliente
    :type timeout: float
    :param system_certs: Si el producto usa el almacén de certificados del sistema
    :type system_certs: bool
    :param env: Variables de entorno que reemplazan a las de ``DEFAULTS``
    :type env: str
    :return: Un generador que entrega un cliente HTTP apuntado al producto
    :rtype: collections.abc.Iterator[httpx.Client]
    """
    settings = {**os.environ, **DEFAULTS, "PYTHONUNBUFFERED": "1", **env}
    command = [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)]
    if system_certs:
        command = [sys.executable, "-c", SYSTEM_CERTS_BOOT.format(port=port)]
    url = f"http://127.0.0.1:{port}"
    with ExitStack() as stack:
        sink = stack.enter_context(log_path.open("wb")) if log_path else None
        server = subprocess.Popen(
            command, cwd=PRODUCT, env=settings, stdout=sink,
            stderr=subprocess.STDOUT if sink else None,
        )
        try:
            for _ in range(40):
                try:
                    httpx.get(f"{url}/health", timeout=1)
                    break
                except httpx.TransportError:
                    time.sleep(0.25)
            yield httpx.Client(
                base_url=url, timeout=timeout, headers={"X-API-Key": FACTORY_KEY}
            )
        finally:
            server.terminate()
            server.wait(timeout=10)
