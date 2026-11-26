"""Ablación de costos: mide calidad, costo y latencia de cada palanca.

Uso::

    python scripts/evaluate.py                    # modelo simulado, sin red
    python scripts/evaluate.py --provider gateway # modelo real (usa .env/entorno)

Corre ``data/eval_set.json`` con cada configuración. Cada pregunta lleva un
historial de relleno, como una conversación larga. Las configuraciones con caché
corren el set dos veces, para que la caché tenga algo que ahorrar; el costo se
reporta por pregunta. Termina con código 1 si la configuración con todas las
palancas pierde calidad o no baja el costo.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# pylint: disable=wrong-import-position
from app.clock import FixedClock  # noqa: E402
from app.config import load_settings  # noqa: E402
from app.llm import ModelUnavailable  # noqa: E402
from app.logs import JsonLogger  # noqa: E402
from app.service import HRService  # noqa: E402

EVAL_SET = ROOT / "data" / "eval_set.json"
TODAY = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)
CACHE_PASSES = 2
OFF = {"ROUTING": "false", "HISTORY_WINDOW": "1000", "COMPACT_PROMPT": "false",
       "CACHE_TTL_SECONDS": "0", "RESPONSE_CACHE_TTL_SECONDS": "0"}
VARIANTS = [
    ("Línea base (sin palancas)", {}),
    ("+ enrutamiento", {"ROUTING": "true"}),
    ("+ ventana de historial", {"HISTORY_WINDOW": "6"}),
    ("+ prompt compacto", {"COMPACT_PROMPT": "true"}),
    ("Palancas sin cachés", {"ROUTING": "true", "HISTORY_WINDOW": "6",
                             "COMPACT_PROMPT": "true"}),
    ("Todas + caché de respuestas", {"ROUTING": "true", "HISTORY_WINDOW": "6",
                                     "COMPACT_PROMPT": "true",
                                     "RESPONSE_CACHE_TTL_SECONDS": "3600"}),
]
GATEWAY_CACHE = ("Todas + caché del gateway", {
    "ROUTING": "true", "HISTORY_WINDOW": "6", "COMPACT_PROMPT": "true",
    "CACHE_TTL_SECONDS": "3600",
})
HISTORY = [
    {"role": role, "content": text}
    for _ in range(5)
    for role, text in (
        ("user", "Hola, necesito datos de un empleado del directorio de RH."),
        ("assistant", "Claro, dime el número de empleado o el departamento."),
    )
]


class Silent:
    """Destino que descarta el log: la evaluación solo imprime su tabla."""

    def write(self, _text):
        """Descarta el texto."""

    def flush(self):
        """No hay nada que vaciar."""


def is_correct(answer: str, case: dict) -> bool:
    """Indica si la respuesta cumple lo que pide el caso."""
    if "must_include" in case:
        return all(text in answer for text in case["must_include"])
    return any(text.lower() in answer.lower() for text in case["any_of"])


def measure(provider: str, overrides: dict, cases: list[dict]) -> dict:
    """Corre el set con una configuración y suma calidad, costo y latencia."""
    env = {**os.environ, **OFF, **overrides, "MODEL_PROVIDER": provider,
           "ENVIRONMENT": "development", "LANGSMITH_TRACING": "false"}
    clock = FixedClock(TODAY)
    logger = JsonLogger("evaluate", clock, stream=Silent())
    service = HRService(load_settings(env), clock=clock, logger=logger)
    uses_cache = any("CACHE" in name and value != "0"
                     for name, value in overrides.items())
    passes = CACHE_PASSES if uses_cache else 1
    correct, cost, tokens, failed = 0, 0.0, 0, []
    started = time.perf_counter()
    for _ in range(passes):
        for case in cases:
            try:
                response = service.ask(case["question"], HISTORY)
            except ModelUnavailable:
                failed.append(f"{case['question']} (modelo no disponible)")
                continue
            good = is_correct(response["answer"], case)
            correct += good
            cost += response["cost_usd"]
            tokens += response["input_tokens"] + response["output_tokens"]
            if not good and case["question"] not in failed:
                failed.append(case["question"])
    total = passes * len(cases)
    return {
        "quality": correct / total, "cost_usd": cost / total,
        "tokens": tokens / total, "passes": passes,
        "latency_ms": 1000 * (time.perf_counter() - started) / total,
        "failed": failed,
    }


def report(provider: str, rows: list[tuple[str, dict]]) -> str:
    """Tabla en Markdown con el ahorro de cada configuración."""
    base = rows[0][1]["cost_usd"]
    lines = [
        f"Proveedor: `{provider}`. Costo y tokens son promedios por pregunta.",
        "",
        "| Configuración | Pasadas | Calidad | Costo USD | Tokens | Latencia | Ahorro |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, result in rows:
        saving = 100 * (1 - result["cost_usd"] / base) if base else 0.0
        lines.append(
            f"| {name} | {result['passes']} | {result['quality']:.0%} | "
            f"{result['cost_usd']:.8f} | {result['tokens']:.0f} | "
            f"{result['latency_ms']:.0f} ms | {saving:.1f} % |"
        )
    for name, result in rows:
        for question in result["failed"]:
            lines.append(f"\nFalló en «{name}»: {question}")
    return "\n".join(lines)


def main() -> int:
    """Corre la ablación, imprime la tabla y decide."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--provider", choices=("fake", "gateway", "workers"), default="fake")
    parser.add_argument("--output", type=Path, help="archivo Markdown de salida")
    args = parser.parse_args()
    cases = json.loads(EVAL_SET.read_text(encoding="utf-8"))
    variants = VARIANTS + ([GATEWAY_CACHE] if args.provider == "gateway" else [])
    rows = [(name, measure(args.provider, env, cases)) for name, env in variants]
    text = report(args.provider, rows)
    print(text)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    baseline, levers = rows[0][1], rows[4][1]
    passed = (levers["quality"] >= baseline["quality"]
              and levers["cost_usd"] < baseline["cost_usd"])
    print(f"\n[{'OK' if passed else 'FAIL'}] misma calidad o mejor, y menos costo")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
