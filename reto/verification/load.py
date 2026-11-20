"""Prueba de carga: muchas preguntas al mismo tiempo, y todas se contestan.

Uso:

- ``uv run python -m verification load``: contra el producto local, con el
  modelo simulado.
- ``uv run python -m verification load <url>``: contra Render. La clave se lee
  de ``SMOKE_API_KEY``, nunca de un argumento.

Pasa si ninguna respuesta es 5xx, si al menos el 95 % son 200 y si el p95 de la
latencia queda por debajo de ``LOAD_P95_MS``. ``LOAD_REQUESTS`` y
``LOAD_CONCURRENCY`` dicen cuántas preguntas y cuántas a la vez.
"""

import asyncio
import math
import os
import sys
import time

import httpx

from verification.server import FACTORY_KEY, running_product

PORT = 8771
QUESTIONS = (
    "¿Quién es EMP-0004?",
    "¿Qué puesto tiene EMP-0005?",
    "¿Quiénes trabajan en el departamento de Finanzas?",
)
MIN_OK_RATIO = 0.95


def percentile(values: list[float], fraction: float) -> float:
    """Percentil por rango más cercano, el mismo método que ``/metrics``."""
    ordered = sorted(values)
    rank = max(1, math.ceil(fraction * len(ordered)))
    return ordered[rank - 1]


async def fire(url, key, total, concurrency, transport=None):
    """Manda ``total`` preguntas, ``concurrency`` a la vez.

    :return: ``(código, milisegundos)`` de cada respuesta
    :rtype: list[tuple[int, float]]
    """
    limit = asyncio.Semaphore(concurrency)
    headers = {"X-API-Key": key}
    async with httpx.AsyncClient(timeout=90, transport=transport) as client:

        async def one(index: int) -> tuple[int, float]:
            question = {"question": QUESTIONS[index % len(QUESTIONS)]}
            async with limit:
                started = time.perf_counter()
                response = await client.post(
                    f"{url}/ask", json=question, headers=headers
                )
                return response.status_code, (time.perf_counter() - started) * 1000

        return await asyncio.gather(*(one(index) for index in range(total)))


def summarize(results, p95_target_ms: float) -> dict:
    """Cuenta códigos, calcula latencias y decide si pasa."""
    codes = [code for code, _ in results]
    latencies = [ms for _, ms in results]
    summary = {
        "requests": len(codes),
        "ok": codes.count(200),
        "server_errors": sum(code >= 500 for code in codes),
        "p50_ms": round(percentile(latencies, 0.5), 1),
        "p95_ms": round(percentile(latencies, 0.95), 1),
    }
    summary["passed"] = (
        summary["server_errors"] == 0
        and summary["ok"] >= MIN_OK_RATIO * summary["requests"]
        and summary["p95_ms"] < p95_target_ms
    )
    return summary


def settings_from_env() -> tuple[int, int, float]:
    """Lee cuántas preguntas, cuántas a la vez y la meta de p95."""
    return (
        int(os.environ.get("LOAD_REQUESTS", "40")),
        int(os.environ.get("LOAD_CONCURRENCY", "8")),
        float(os.environ.get("LOAD_P95_MS", "5000")),
    )


def main(args: list[str]) -> int:
    """Corre la carga local o contra la URL; 0 si pasa."""
    total, concurrency, target = settings_from_env()
    if args:
        key = os.environ.get("SMOKE_API_KEY", "")
        if not key:
            print(
                "Uso (PowerShell): $env:SMOKE_API_KEY = '<clave>' y luego "
                "uv run python -m verification load <url>"
            )
            return 2
        results = asyncio.run(fire(args[0].rstrip("/"), key, total, concurrency))
    else:
        with running_product(PORT) as client:
            url = str(client.base_url).rstrip("/")
            results = asyncio.run(fire(url, FACTORY_KEY, total, concurrency))
    summary = summarize(results, target)
    print(
        f"  requests={summary['requests']} concurrency={concurrency} "
        f"ok={summary['ok']} server_errors={summary['server_errors']} "
        f"p50_ms={summary['p50_ms']} p95_ms={summary['p95_ms']}"
    )
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
