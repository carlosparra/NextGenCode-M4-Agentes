"""Prueba de carga: muchas peticiones concurrentes contra la API.

Uso::

    export LOAD_API_KEY='<clave>'
    python scripts/load_test.py http://127.0.0.1:8000 --requests 200 --concurrency 20

Mide rendimiento (peticiones por segundo), latencia p50/p95/p99 y códigos de
respuesta. Con el modelo simulado mide la capacidad de la plataforma; con el
real, la del sistema completo (cuidado con la cuota del proveedor).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from collections import Counter
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# pylint: disable=wrong-import-position
from app.observability.metrics import percentile  # noqa: E402

QUESTIONS = (
    "¿Quién es EMP-0004?",
    "¿Cuántas vacaciones le quedan a EMP-0001?",
    "¿Quiénes trabajan en Finanzas?",
    "Resume el área de Ventas",
)


async def worker(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    client, url, key, queue, latencies, codes
):
    """Toma peticiones de la cola hasta vaciarla."""
    while True:
        try:
            index = queue.get_nowait()
        except asyncio.QueueEmpty:
            return
        question = QUESTIONS[index % len(QUESTIONS)]
        start = time.perf_counter()
        try:
            response = await client.post(
                f"{url}/ask", json={"question": question}, headers={"X-API-Key": key}
            )
            codes[response.status_code] += 1
        except httpx.HTTPError as exc:
            codes[type(exc).__name__] += 1
        latencies.append((time.perf_counter() - start) * 1000)


async def run(url: str, key: str, total: int, concurrency: int) -> dict:
    """Lanza ``total`` peticiones con ``concurrency`` clientes a la vez."""
    queue: asyncio.Queue = asyncio.Queue()
    for index in range(total):
        queue.put_nowait(index)
    latencies: list[float] = []
    codes: Counter = Counter()
    limits = httpx.Limits(max_connections=concurrency)
    async with httpx.AsyncClient(timeout=120, limits=limits) as client:
        started = time.perf_counter()
        await asyncio.gather(
            *(
                worker(client, url, key, queue, latencies, codes)
                for _ in range(concurrency)
            )
        )
        elapsed = time.perf_counter() - started
    return {
        "requests": total,
        "concurrency": concurrency,
        "seconds": round(elapsed, 2),
        "rps": round(total / elapsed, 1),
        "p50_ms": percentile(latencies, 0.5),
        "p95_ms": percentile(latencies, 0.95),
        "p99_ms": percentile(latencies, 0.99),
        "codes": dict(codes),
    }


def main() -> int:
    """Punto de entrada."""
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=20)
    args = parser.parse_args()
    key = os.environ.get("LOAD_API_KEY", "")
    if not key:
        print("Define LOAD_API_KEY con una clave válida")
        return 2
    result = asyncio.run(
        run(args.url.rstrip("/"), key, args.requests, args.concurrency)
    )
    for name, value in result.items():
        print(f"{name:12} {value}")
    return 0 if set(result["codes"]) <= {200, 429} else 1


if __name__ == "__main__":
    sys.exit(main())
