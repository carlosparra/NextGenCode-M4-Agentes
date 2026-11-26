"""Prueba de carga corta: muchas preguntas a la vez contra ``/ask``.

Uso::

    LOAD_API_KEY=... python scripts/load_test.py http://127.0.0.1:8000 \
        --requests 200 --concurrency 20

Reporta códigos de respuesta, peticiones por segundo y latencias p50, p95 y p99.
"""

import argparse
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import httpx

QUESTIONS = [
    "¿Quién es EMP-0004?",
    "¿Quiénes trabajan en Finanzas?",
    "¿Cuántas vacaciones le quedan a EMP-0001?",
    "Resume el departamento de Tecnología",
]


def percentile(values: list[float], fraction: float) -> float:
    """Percentil por rango más cercano."""
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]


def main() -> int:
    """Lanza la carga e imprime el resumen; 0 si no hubo errores 5xx."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("url")
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=20)
    args = parser.parse_args()
    headers = {"X-API-Key": os.environ.get("LOAD_API_KEY", "")}
    url = args.url.rstrip("/") + "/ask"

    def one(number: int) -> tuple[int, float]:
        body = {"question": QUESTIONS[number % len(QUESTIONS)]}
        started = time.perf_counter()
        status = client.post(url, json=body, headers=headers).status_code
        return status, 1000 * (time.perf_counter() - started)

    limits = httpx.Limits(max_connections=args.concurrency)
    with httpx.Client(timeout=60, limits=limits) as client:
        started = time.perf_counter()
        with ThreadPoolExecutor(args.concurrency) as pool:
            results = list(pool.map(one, range(args.requests)))
        elapsed = time.perf_counter() - started
    codes = Counter(status for status, _ in results)
    latencies = [latency for _, latency in results]
    print(f"peticiones={args.requests} concurrencia={args.concurrency} "
          f"duración={elapsed:.2f}s rps={args.requests / elapsed:.1f}")
    print("códigos: " + ", ".join(f"{code}={n}" for code, n in sorted(codes.items())))
    print(f"latencia ms: p50={percentile(latencies, 0.5):.1f} "
          f"p95={percentile(latencies, 0.95):.1f} "
          f"p99={percentile(latencies, 0.99):.1f} max={max(latencies):.1f}")
    return 0 if not any(code >= 500 for code in codes) else 1


if __name__ == "__main__":
    sys.exit(main())
