"""Compara costo y calidad: línea base contra la configuración con palancas.

Corre ``verification/eval_set.json`` contra el producto dos veces. Cada pregunta
lleva un historial de relleno, como una conversación larga. Pasa solo si la
calidad no baja y el costo sí baja.

Sin argumentos usa el modelo simulado (es la compuerta de la fábrica). Con
``--real`` usa el modelo de Cloudflare a través del gateway: lee
``CF_ACCOUNT_ID`` y ``CF_API_TOKEN`` del entorno de la terminal, repite cada
configuración varias veces, agrega una fila con la caché del gateway y guarda
la tabla en ``output/evaluate-real.md``. Nunca imprime ni guarda esas variables.
"""

import json
import os
import sys
from pathlib import Path

from verification.server import running_product

ROOT = Path(__file__).resolve().parent.parent
EVAL_SET = Path(__file__).resolve().parent / "eval_set.json"
REAL_REPORT = ROOT / "output" / "evaluate-real.md"
BASELINE = {"ROUTING": "false", "HISTORY_WINDOW": "1000"}
HISTORY = [
    {"role": role, "content": text}
    for _ in range(5)
    for role, text in (
        ("user", "Hola, necesito datos de un empleado del directorio de RH."),
        ("assistant", "Claro, dime el número de empleado o el departamento."),
    )
]
PORT = 8767
# Con el modelo real cada llamada tarda segundos, no milisegundos
REAL_TIMEOUT = 90
REAL_REPEATS = 3
CACHE_SECONDS = "300"
CREDENTIALS = ("CF_ACCOUNT_ID", "CF_API_TOKEN")
# Nombre de la configuración y las variables que la distinguen
REAL_CONFIGS = {
    "baseline": BASELINE,
    "levers": {},
    "levers + cache": {"CACHE_TTL_SECONDS": CACHE_SECONDS},
}


def load_cases() -> list[dict]:
    """Lee los casos de evaluación.

    :return: Casos de ``eval_set.json``
    :rtype: list[dict]
    """
    return json.loads(EVAL_SET.read_text(encoding="utf-8"))


def is_correct(answer: str, case: dict) -> bool:
    """Indica si la respuesta cumple lo que pide el caso de evaluación.

    :param answer: Texto de la respuesta del producto
    :type answer: str
    :param case: Caso con ``must_include`` (todos los textos) o ``any_of`` (alguno)
    :type case: dict
    :return: ``True`` si la respuesta cumple el caso
    :rtype: bool
    """
    if "must_include" in case:
        return all(text in answer for text in case["must_include"])
    return any(text.lower() in answer.lower() for text in case["any_of"])


def measure(client, cases: list[dict]) -> dict:
    """Pregunta cada caso y suma calidad, costo y fallas.

    Una llamada que no responde 200 cuenta como falla y como respuesta
    incorrecta; no suma costo ni tokens.

    :param client: Cliente HTTP ya apuntado al producto y con su clave
    :type client: httpx.Client
    :param cases: Casos de ``eval_set.json``
    :type cases: list[dict]
    :return: ``quality`` (fracción correcta), ``cost_usd``, ``input_tokens`` y
        ``errors`` (llamadas que no respondieron 200)
    :rtype: dict
    """
    correct, cost, tokens, errors = 0, 0.0, 0, 0
    for case in cases:
        response = client.post(
            "/ask", json={"question": case["question"], "history": HISTORY}
        )
        if response.status_code != 200:
            errors += 1
            continue
        body = response.json()
        correct += is_correct(body["answer"], case)
        cost += body["cost_usd"]
        tokens += body["input_tokens"]
    return {
        "quality": correct / len(cases), "cost_usd": cost,
        "input_tokens": tokens, "errors": errors,
    }


def verdict(baseline: dict, levers: dict) -> bool:
    """La regla de la sesión: misma calidad o mejor, y menos costo.

    :param baseline: Resultado de la línea base, de :func:`measure`
    :type baseline: dict
    :param levers: Resultado con las palancas, de :func:`measure`
    :type levers: dict
    :return: ``True`` si la calidad no baja y el costo sí baja
    :rtype: bool
    """
    return levers["quality"] >= baseline["quality"] and (
        levers["cost_usd"] < baseline["cost_usd"]
    )


def missing_credentials(env) -> list[str]:
    """Nombra las credenciales del gateway que faltan o están vacías.

    Solo devuelve nombres de variables, nunca sus valores.

    :param env: Variables de entorno (``os.environ`` o un diccionario)
    :type env: collections.abc.Mapping
    :return: Nombres de las variables ausentes, en el orden de ``CREDENTIALS``
    :rtype: list[str]
    """
    return [name for name in CREDENTIALS if not env.get(name)]


def summarize(runs: list[dict]) -> dict:
    """Resume varias repeticiones de una misma configuración.

    :param runs: Resultados de :func:`measure`, uno por repetición
    :type runs: list[dict]
    :return: ``quality`` (media), ``worst_quality``, ``cost_usd`` e
        ``input_tokens`` (medias por repetición) y ``errors`` (suma)
    :rtype: dict
    """
    count = len(runs)
    return {
        "quality": sum(run["quality"] for run in runs) / count,
        "worst_quality": min(run["quality"] for run in runs),
        "cost_usd": sum(run["cost_usd"] for run in runs) / count,
        "input_tokens": sum(run["input_tokens"] for run in runs) / count,
        "errors": sum(run["errors"] for run in runs),
    }


def render_report(results: dict[str, dict], passed: bool) -> str:
    """Arma la tabla en Markdown con el resultado de cada configuración.

    :param results: Nombre de la configuración y su :func:`summarize`
    :type results: dict[str, dict]
    :param passed: Si las palancas mantienen la calidad y bajan el costo
    :type passed: bool
    :return: Texto Markdown con la tabla y el veredicto
    :rtype: str
    """
    rows = [
        f"| {name} | {item['quality']:.0%} | {item['worst_quality']:.0%} | "
        f"{item['cost_usd']:.6f} | {item['input_tokens']:.0f} | {item['errors']} |"
        for name, item in results.items()
    ]
    return "\n".join([
        "# Evaluación con el modelo real",
        "",
        f"Cada configuración se repitió {REAL_REPEATS} veces; costo y tokens son",
        "por repetición (todas las preguntas del conjunto).",
        "",
        "| Configuración | Calidad media | Peor calidad | Costo (USD) "
        "| Tokens de entrada | Errores |",
        "| --- | --- | --- | --- | --- | --- |",
        *rows,
        "",
        f"Veredicto: {'PASA' if passed else 'NO PASA'} (las palancas mantienen "
        "la calidad media y bajan el costo, sin contar la caché).",
        "",
    ])


def run_real() -> int:
    """Mide las tres configuraciones con el modelo real y guarda la tabla.

    :return: 0 si las palancas mantienen la calidad y bajan el costo, 1 si no y 2
        si faltan las credenciales del gateway en el entorno
    :rtype: int
    """
    missing = missing_credentials(os.environ)
    if missing:
        print(f"Faltan en el entorno: {', '.join(missing)}")
        return 2
    cases = load_cases()
    results = {}
    for name, extra in REAL_CONFIGS.items():
        # Un solo producto por configuración: la caché necesita las repeticiones
        with running_product(
            PORT, timeout=REAL_TIMEOUT, system_certs=True,
            MODEL_PROVIDER="gateway", **extra,
        ) as client:
            runs = [measure(client, cases) for _ in range(REAL_REPEATS)]
        results[name] = summarize(runs)
    passed = verdict(results["baseline"], results["levers"])
    report = render_report(results, passed)
    REAL_REPORT.parent.mkdir(parents=True, exist_ok=True)
    REAL_REPORT.write_text(report, encoding="utf-8")
    print(report)
    return 0 if passed else 1


def run_fake() -> int:
    """Mide las dos configuraciones con el modelo simulado y decide.

    :return: 0 si las palancas mantienen la calidad y bajan el costo; 1 si no
    :rtype: int
    """
    cases = load_cases()
    with running_product(PORT, **BASELINE) as client:
        baseline = measure(client, cases)
    with running_product(8768) as client:
        levers = measure(client, cases)
    for name, result in (("baseline", baseline), ("levers", levers)):
        print(
            f"{name:9} quality={result['quality']:.0%} "
            f"cost_usd={result['cost_usd']:.6f} input_tokens={result['input_tokens']}"
        )
    return 0 if verdict(baseline, levers) else 1


def main(args: list[str] | None = None) -> int:
    """Elige el modo: simulado por omisión, real con ``--real``.

    :param args: Argumentos de la línea de comandos; ``None`` usa ``sys.argv``
    :type args: list[str] or None
    :return: Código de salida del modo elegido
    :rtype: int
    """
    args = sys.argv[1:] if args is None else args
    return run_real() if "--real" in args else run_fake()


if __name__ == "__main__":
    sys.exit(main())
