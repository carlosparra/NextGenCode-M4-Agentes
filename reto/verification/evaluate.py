"""Compara costo y calidad: línea base, palancas y palancas con caché.

Corre ``verification/eval_set.json`` contra el producto tres veces, con el
modelo simulado. Cada pregunta lleva un historial de relleno, como una
conversación larga, y se hace ``ROUNDS`` veces, como en un portal donde muchas
personas preguntan lo mismo. Pasa solo si en cada paso la calidad no baja y el
costo sí baja.
"""

import json
import sys
from pathlib import Path

from verification.server import running_product

EVAL_SET = Path(__file__).resolve().parent / "eval_set.json"
BASELINE = {"ROUTING": "false", "HISTORY_WINDOW": "1000"}
CACHED = {"RESPONSE_CACHE_TTL_SECONDS": "300"}
CONFIGS = (("baseline", 8767, BASELINE), ("levers", 8768, {}), ("cache", 8772, CACHED))
ROUNDS = 2
HISTORY = [
    {"role": role, "content": text}
    for _ in range(5)
    for role, text in (
        ("user", "Hola, necesito datos de un empleado del directorio de RH."),
        ("assistant", "Claro, dime el número de empleado o el departamento."),
    )
]


def is_correct(answer: str, case: dict) -> bool:
    """Indica si la respuesta cumple lo que pide el caso de evaluación."""
    if "must_include" in case:
        return all(text in answer for text in case["must_include"])
    return any(text.lower() in answer.lower() for text in case["any_of"])


def measure(client, cases: list[dict], rounds: int = 1) -> dict:
    """Pregunta cada caso ``rounds`` veces y suma calidad y costo.

    :return: ``quality`` (fracción correcta), ``cost_usd`` e ``input_tokens``
    :rtype: dict
    """
    correct, cost, tokens, asked = 0, 0.0, 0, 0
    for _ in range(rounds):
        for case in cases:
            body = client.post(
                "/ask", json={"question": case["question"], "history": HISTORY}
            ).json()
            correct += is_correct(body["answer"], case)
            cost += body["cost_usd"]
            tokens += body["input_tokens"]
            asked += 1
    return {"quality": correct / asked, "cost_usd": cost, "input_tokens": tokens}


def reduction(baseline: dict, other: dict) -> float:
    """Fracción del costo de la línea base que se ahorra."""
    if baseline["cost_usd"] == 0:
        return 0.0
    return 1 - other["cost_usd"] / baseline["cost_usd"]


def verdict(baseline: dict, levers: dict) -> bool:
    """La regla de la sesión: misma calidad o mejor, y menos costo."""
    return levers["quality"] >= baseline["quality"] and (
        levers["cost_usd"] < baseline["cost_usd"]
    )


def main() -> int:
    """Mide las tres configuraciones, imprime la tabla y decide."""
    cases = json.loads(EVAL_SET.read_text(encoding="utf-8"))
    results = {}
    for name, port, env in CONFIGS:
        with running_product(port, **env) as client:
            results[name] = measure(client, cases, ROUNDS)
    for name, result in results.items():
        print(
            f"{name:9} quality={result['quality']:.0%} "
            f"cost_usd={result['cost_usd']:.6f} "
            f"input_tokens={result['input_tokens']} "
            f"ahorro={reduction(results['baseline'], result):.0%}"
        )
    passed = verdict(results["baseline"], results["levers"]) and verdict(
        results["levers"], results["cache"]
    )
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
