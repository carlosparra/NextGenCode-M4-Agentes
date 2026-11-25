"""Evaluación de costo y calidad: línea base contra cada palanca (ablación).

Corre el set de evaluación con distintas configuraciones y deja una tabla con
calidad, tokens, costo, llamadas al modelo y latencia. Una palanca solo se
acepta si la calidad no baja.

Uso::

    python scripts/evaluate.py --fake-only      # sin red ni costo (CI)
    python scripts/evaluate.py --real           # además con Cloudflare (.env)

Resultados en ``evidence/costs/``.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# pylint: disable=wrong-import-position
from app.clock import SystemClock  # noqa: E402
from app.config import load_settings  # noqa: E402
from app.mcp_server.__main__ import load_env_file  # noqa: E402
from app.observability.logs import JsonLogger, request_id_var  # noqa: E402
from app.observability.tracing import Tracer  # noqa: E402
from app.service import HrService, build_services  # noqa: E402

EVAL_SET = ROOT / "scripts" / "eval_set.json"
OUT = ROOT / "evidence" / "costs"
HISTORY = [
    {"role": role, "content": text}
    for _ in range(5)
    for role, text in (
        ("user", "Hola, necesito datos de un empleado del directorio de RH."),
        ("assistant", "Claro, dime el número de empleado o el departamento."),
    )
]
BASELINE = {
    "ROUTING": "false",
    "HISTORY_WINDOW": "1000",
    "COMPACT_PROMPTS": "false",
    "ANSWER_CACHE_TTL_SECONDS": "0",
    "CACHE_TTL_SECONDS": "0",
}
# Subconjunto para el modelo real: cubre cada intención sin agotar la cuota gratuita
REAL_CASES = (0, 2, 6, 7, 8, 10, 11, 13, 14)
LEVERS = {
    "routing": {"ROUTING": "true"},
    "history_window": {"HISTORY_WINDOW": "6"},
    "compact_prompts": {"COMPACT_PROMPTS": "true"},
    "answer_cache": {"ANSWER_CACHE_TTL_SECONDS": "300"},
}


def is_correct(answer: str, case: dict) -> bool:
    """Indica si la respuesta cumple el caso.

    :param answer: Respuesta del asistente
    :type answer: str
    :param case: Caso con ``must_include`` o ``any_of``
    :type case: dict
    :return: ``True`` si es correcta
    :rtype: bool
    """
    if "must_include" in case:
        return all(text in answer for text in case["must_include"])
    return any(text.lower() in answer.lower() for text in case["any_of"])


async def measure(  # pylint: disable=too-many-locals
    env: dict, cases: list[dict], passes: int
) -> dict:
    """Corre el set ``passes`` veces con una configuración.

    La segunda pasada simula preguntas repetidas (lo que aprovechan las cachés).

    :param env: Variables de entorno de la corrida
    :type env: dict
    :param cases: Casos de evaluación
    :type cases: list[dict]
    :param passes: Pasadas por el set
    :type passes: int
    :return: Calidad, tokens, costo, llamadas y latencia
    :rtype: dict
    """
    clock = SystemClock()
    settings = load_settings(env)
    tracer = Tracer(settings, env=env)
    service = HrService(
        build_services(
            settings, clock, JsonLogger("eval", clock, io.StringIO()), tracer=tracer
        )
    )
    correct = total = tokens_in = tokens_out = calls = 0
    cost = latency = 0.0
    failures = []
    for number in range(passes):
        for index, case in enumerate(cases):
            request_id_var.set(f"eval-{number}-{index}")
            body = await service.ask(case["question"], HISTORY)
            ok = is_correct(body["answer"], case)
            correct += ok
            total += 1
            tokens_in += body["input_tokens"]
            tokens_out += body["output_tokens"]
            calls += body["model_calls"]
            cost += body["cost_usd"]
            latency += body["latency_ms"]
            if not ok:
                failures.append(
                    {"question": case["question"], "answer": body["answer"]}
                )
    tracer.flush()
    return {
        "quality": round(correct / total, 4),
        "input_tokens": tokens_in,
        "output_tokens": tokens_out,
        "model_calls": calls,
        "cost_usd": round(cost, 8),
        "avg_latency_ms": round(latency / total, 1),
        "failures": failures,
    }


def table(rows: list[tuple[str, dict]], baseline: dict) -> str:
    """Tabla Markdown con el ahorro contra la línea base."""
    lines = [
        "| Configuración | Calidad | Tokens entrada | Tokens salida | Llamadas | "
        "Costo USD | Ahorro | Latencia media ms |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, result in rows:
        saving = (
            1 - result["cost_usd"] / baseline["cost_usd"] if baseline["cost_usd"] else 0
        )
        lines.append(
            f"| {name} | {result['quality']:.0%} | {result['input_tokens']} | "
            f"{result['output_tokens']} | {result['model_calls']} | "
            f"{result['cost_usd']:.6f} | {saving:.1%} | {result['avg_latency_ms']} |"
        )
    return "\n".join(lines)


async def run_suite(base_env: dict, cases: list[dict], label: str, full: bool) -> bool:
    """Corre línea base, cada palanca sola y todas juntas; escribe la evidencia.

    :return: ``True`` si con todas las palancas la calidad no baja y el costo sí
    :rtype: bool
    """
    passes = 2
    baseline = await measure({**base_env, **BASELINE}, cases, passes)
    rows = [("línea base", baseline)]
    if full:
        for name, lever in LEVERS.items():
            rows.append(
                (
                    f"+ {name}",
                    await measure({**base_env, **BASELINE, **lever}, cases, passes),
                )
            )
    combined = {k: v for lever in LEVERS.values() for k, v in lever.items()}
    levers = await measure({**base_env, **BASELINE, **combined}, cases, passes)
    rows.append(("todas las palancas de la app", levers))
    if base_env.get("MODEL_PROVIDER") == "gateway":
        gateway_cache = {**combined, "CACHE_TTL_SECONDS": "3600"}
        rows.append(
            (
                "+ caché de AI Gateway",
                await measure({**base_env, **BASELINE, **gateway_cache}, cases, passes),
            )
        )
    OUT.mkdir(parents=True, exist_ok=True)
    markdown = table(rows, baseline)
    (OUT / f"{label}.md").write_text(
        f"# Evaluación de costos ({label})\n\n{len(cases)} preguntas x {passes} "
        f"pasadas, con 10 mensajes de historial.\n\n{markdown}\n",
        encoding="utf-8",
    )
    (OUT / f"{label}.json").write_text(
        json.dumps(dict(rows), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n## {label}\n{markdown}")
    passed = levers["quality"] >= baseline["quality"] and (
        levers["cost_usd"] < baseline["cost_usd"]
    )
    print(
        f"[{'OK' if passed else 'FAIL'}] {label}: misma calidad o mejor y menos costo"
    )
    return passed


def main() -> int:
    """Punto de entrada."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--fake-only", action="store_true")
    parser.add_argument("--real", action="store_true", help="también con Cloudflare")
    args = parser.parse_args()
    cases = json.loads(EVAL_SET.read_text(encoding="utf-8"))
    fake_env = {"MODEL_PROVIDER": "fake", "LANGSMITH_TRACING": "false"}
    ok = asyncio.run(run_suite(fake_env, cases, "fake", full=True))
    if args.real and not args.fake_only:
        env = {**os.environ, **load_env_file(ROOT / ".env")}
        env.update(MODEL_PROVIDER="gateway", LANGSMITH_PROJECT="hr-assistant-eval")
        subset = [cases[index] for index in REAL_CASES]
        ok = asyncio.run(run_suite(env, subset, "cloudflare", full=False)) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
