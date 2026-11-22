"""Prueba de carga por escalones con Locust.

Uso, con Locust prestado por ``uv`` (no se instala en el proyecto):

- ``uv run --with locust python -m verification.load local``: levanta el producto
  con el modelo simulado y un límite de peticiones muy alto, y mide la capacidad
  de la aplicación sola.
- ``SMOKE_API_KEY=<clave> uv run --with locust python -m verification.load render
  <url>``: mide el servicio publicado con el modelo real y un perfil bajo, más un
  escalón final que supera a propósito el límite por cliente.

Guarda ``output/load-<perfil>.md``. La clave viaja por el entorno, nunca por la
línea de comandos, y no se imprime ni se guarda.
"""

import csv
import importlib.util
import io
import os
import random
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from verification import production
from verification.server import FACTORY_KEY, running_product

ROOT = Path(__file__).resolve().parent.parent
LOCUSTFILE = Path(__file__).resolve().parent / "locustfile.py"
REPORT_DIR = ROOT / "output"
LOCAL_PORT = 8773
SLO_MS = 2000
# Un poco más que la ventana de un minuto del límite por cliente
RETRY_SECONDS = 61
KEY_VARIABLE = "SMOKE_API_KEY"
ASK_NAME = "POST /ask"
AGGREGATED = "Aggregated"
DEPARTMENTS = ("Finanzas", "Tecnología")
EMPLOYEE_SHARE = 0.60
DEPARTMENT_SHARE = 0.85


@dataclass(frozen=True)
class Step:
    """Un escalón de la prueba: cuántos usuarios, cuánto tiempo y a qué ritmo.

    :param users: Usuarios simultáneos
    :type users: int
    :param seconds: Duración del escalón en segundos
    :type seconds: int
    :param wait_min: Pausa mínima entre las preguntas de un usuario, en segundos
    :type wait_min: float
    :param wait_max: Pausa máxima entre las preguntas de un usuario, en segundos
    :type wait_max: float
    :param overflow: Si el escalón supera a propósito el límite por cliente
    :type overflow: bool
    """

    users: int
    seconds: int
    wait_min: float
    wait_max: float
    overflow: bool = False


# Local: sin límite, para ver dónde se doblan los hilos de la aplicación.
# Render: pausas largas para quedar bajo el límite por cliente; el último
# escalón lo supera a propósito para ver el 429.
PROFILES = {
    "local": [Step(users, 60, 0.1, 0.5) for users in (1, 5, 10, 20, 50, 100)],
    "render": [
        *(Step(users, 90, 8.0, 12.0) for users in (1, 2, 3)),
        Step(10, 30, 1.0, 2.0, overflow=True),
    ],
}


def request_name(status) -> str:
    """Nombre con el que Locust cuenta una petición según su resultado.

    :param status: Código HTTP, o un texto como ``error`` si no hubo respuesta
    :type status: int or str
    :return: Nombre, por ejemplo ``POST /ask [200]``
    :rtype: str
    """
    return f"{ASK_NAME} [{status}]"


def pick_question(rng) -> str:
    """Elige una pregunta: por empleado, por departamento o con datos inventados.

    :param rng: Generador con ``random()``, ``randint()`` y ``choice()``
    :type rng: random.Random or module
    :return: Texto de la pregunta
    :rtype: str
    """
    draw = rng.random()
    if draw < EMPLOYEE_SHARE:
        return f"¿Quién es EMP-{rng.randint(1, 5):04d}?"
    if draw < DEPARTMENT_SHARE:
        department = rng.choice(DEPARTMENTS)
        return f"¿Quiénes trabajan en el departamento de {department}?"
    return production.PII_QUESTION


def _latency(text: str):
    """Convierte una latencia del CSV; Locust escribe ``N/A`` si no hubo datos.

    :param text: Valor de la celda
    :type text: str
    :return: Milisegundos, o ``None`` si no hay dato
    :rtype: float or None
    """
    return None if text.strip().upper() == "N/A" else float(text)


def parse_stats(text: str) -> dict[str, dict]:
    """Lee el CSV de estadísticas de Locust.

    :param text: Contenido de ``<prefijo>_stats.csv``
    :type text: str
    :return: Por nombre de petición: ``count``, ``failures``, ``rps``, ``p50``,
        ``p95`` y ``p99`` (estas tres, ``None`` si no hubo peticiones terminadas)
    :rtype: dict[str, dict]
    """
    rows = {}
    for row in csv.DictReader(io.StringIO(text)):
        rows[row["Name"]] = {
            "count": int(row["Request Count"]),
            "failures": int(row["Failure Count"]),
            "rps": float(row["Requests/s"]),
            "p50": _latency(row["50%"]),
            "p95": _latency(row["95%"]),
            "p99": _latency(row["99%"]),
        }
    return rows


def _count(rows: dict, status) -> int:
    """Peticiones contadas con un resultado.

    :param rows: Resultado de :func:`parse_stats`
    :type rows: dict
    :param status: Código HTTP o ``error``
    :type status: int or str
    :return: Número de peticiones, 0 si no hubo
    :rtype: int
    """
    return rows.get(request_name(status), {}).get("count", 0)


def summarize_step(users: int, rows: dict) -> dict:
    """Resume un escalón: totales, resultados y latencia de las respuestas 200.

    :param users: Usuarios simultáneos del escalón
    :type users: int
    :param rows: Resultado de :func:`parse_stats`
    :type rows: dict
    :return: ``users``, ``requests``, ``rps``, ``ok``, ``rate_limited``,
        ``unavailable``, ``other_errors`` y ``p50``, ``p95``, ``p99`` (``None`` si
        no hubo respuestas 200)
    :rtype: dict
    """
    total = rows.get(AGGREGATED, {})
    requests = total.get("count", sum(item["count"] for item in rows.values()))
    ok_row = rows.get(request_name(200))
    ok, limited, unavailable = _count(rows, 200), _count(rows, 429), _count(rows, 502)
    return {
        "users": users,
        "requests": requests,
        "rps": total.get("rps", 0.0),
        "ok": ok,
        "rate_limited": limited,
        "unavailable": unavailable,
        "other_errors": requests - ok - limited - unavailable,
        "p50": ok_row["p50"] if ok_row else None,
        "p95": ok_row["p95"] if ok_row else None,
        "p99": ok_row["p99"] if ok_row else None,
    }


def meets_slo(step: dict, slo_ms: float) -> bool:
    """Indica si un escalón cumple la meta de latencia sin errores del servicio.

    Los ``429`` no cuentan como error: son la respuesta esperada al límite.

    :param step: Resultado de :func:`summarize_step`
    :type step: dict
    :param slo_ms: Meta de latencia p95 en milisegundos
    :type slo_ms: float
    :return: ``True`` si el p95 de las respuestas 200 está dentro de la meta y no
        hubo ``502`` ni otros errores
    :rtype: bool
    """
    return (
        step["p95"] is not None and step["p95"] <= slo_ms
        and step["unavailable"] == 0 and step["other_errors"] == 0
    )


def largest_compliant(steps: list[dict], slo_ms: float):
    """El mayor número de usuarios de un escalón normal que cumple la meta.

    :param steps: Escalones resumidos, cada uno con la clave ``overflow``
    :type steps: list[dict]
    :param slo_ms: Meta de latencia p95 en milisegundos
    :type slo_ms: float
    :return: Usuarios del mejor escalón, o ``None`` si ninguno cumple
    :rtype: int or None
    """
    users = [
        step["users"] for step in steps
        if not step["overflow"] and meets_slo(step, slo_ms)
    ]
    return max(users) if users else None


def locust_command(step: Step, host: str, prefix: str) -> list[str]:
    """Arma la orden de Locust para un escalón; la clave no va aquí.

    :param step: Escalón a correr
    :type step: Step
    :param host: Dirección base del servicio
    :type host: str
    :param prefix: Prefijo de los archivos CSV que escribe Locust
    :type prefix: str
    :return: Orden como lista de argumentos
    :rtype: list[str]
    """
    return [
        sys.executable, "-m", "locust", "-f", str(LOCUSTFILE), "--headless",
        "--only-summary", "-u", str(step.users), "-r", str(step.users),
        "-t", f"{step.seconds}s", "--host", host, "--csv", prefix,
    ]


def time_first_response(client, url: str):
    """Mide cuánto tarda en responder ``/health``; despierta un servicio dormido.

    :param client: Cliente HTTP
    :type client: httpx.Client
    :param url: Dirección base del servicio
    :type url: str
    :return: Segundos que tardó, o ``None`` si no hubo respuesta
    :rtype: float or None
    """
    started = time.monotonic()
    try:
        client.get(f"{url}/health")
    except httpx.HTTPError:
        return None
    return time.monotonic() - started


def read_metrics(client, url: str, key: str):
    """Lee ``/metrics`` del servicio con la clave dada.

    :param client: Cliente HTTP
    :type client: httpx.Client
    :param url: Dirección base del servicio
    :type url: str
    :param key: Clave de cliente para ``X-API-Key``
    :type key: str
    :return: ``requests``, ``error_rate``, ``p95_ms``, ``cost_usd`` y
        ``slo_met``, o ``None`` si no se pudo leer
    :rtype: dict or None
    """
    try:
        response = client.get(f"{url}/metrics", headers={"X-API-Key": key})
        body = response.json()
        if response.status_code != 200:
            return None
        return {
            "requests": body["requests"],
            "error_rate": body["error_rate"],
            "p95_ms": body["latency_ms"]["p95"],
            "cost_usd": body["cost_usd"],
            "slo_met": body["slo"]["met"],
        }
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return None


def read_metrics_after_limit(client, url: str, key: str, sleep=time.sleep):
    """Lee ``/metrics``; si el límite del minuto está agotado, espera y reintenta.

    ``/metrics`` cuenta como una petición del cliente, y el último escalón agota
    a propósito el límite: sin la espera, ese ``429`` dejaría el informe sin las
    cifras del servicio.

    :param client: Cliente HTTP
    :type client: httpx.Client
    :param url: Dirección base del servicio
    :type url: str
    :param key: Clave de cliente para ``X-API-Key``
    :type key: str
    :param sleep: Función que espera los segundos dados; se inyecta en las pruebas
    :type sleep: collections.abc.Callable
    :return: Lo mismo que :func:`read_metrics`, tras un único reintento
    :rtype: dict or None
    """
    metrics = read_metrics(client, url, key)
    if metrics is None:
        sleep(RETRY_SECONDS)
        metrics = read_metrics(client, url, key)
    return metrics


def execute(profile: list[Step], runner) -> list[dict]:
    """Corre cada escalón con ``runner`` y resume su resultado.

    :param profile: Escalones, en orden
    :type profile: list[Step]
    :param runner: Función que corre un escalón y devuelve el texto del CSV
    :type runner: collections.abc.Callable
    :return: Escalones resumidos, con la clave ``overflow``
    :rtype: list[dict]
    """
    steps = []
    for step in profile:
        summary = summarize_step(step.users, parse_stats(runner(step)))
        summary["overflow"] = step.overflow
        steps.append(summary)
    return steps


def _ms(value) -> str:
    """Formatea milisegundos, o un guion si no hay dato."""
    return "-" if value is None else f"{value:.0f}"


def _row(step: dict, slo_ms: float) -> str:
    """Una fila de la tabla del informe."""
    if step["overflow"]:
        note = "(límite) supera a propósito el límite por cliente"
    else:
        note = "cumple" if meets_slo(step, slo_ms) else "no cumple"
    return (
        f"| {step['users']} | {step['requests']} | {step['rps']:.2f} | "
        f"{_ms(step['p50'])} | {_ms(step['p95'])} | {_ms(step['p99'])} | "
        f"{step['ok']} | {step['rate_limited']} | {step['unavailable']} | "
        f"{step['other_errors']} | {note} |"
    )


def _metrics_lines(target, metrics) -> list[str]:
    """Las líneas del informe con lo que dice ``/metrics``."""
    if metrics is None:
        return ["No se pudo leer `/metrics` del servicio."]
    fictitious = (
        ["El costo sale del modelo simulado: no es gasto real."]
        if target == "local" else []
    )
    return [
        f"Según `/metrics`: {metrics['requests']} peticiones desde que arrancó el "
        f"proceso, tasa de error {metrics['error_rate']:.1%}, p95 "
        f"{metrics['p95_ms']} ms, costo acumulado {metrics['cost_usd']} USD y "
        f"meta de latencia {'cumplida' if metrics['slo_met'] else 'no cumplida'}.",
        *fictitious,
    ]


def render_report(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    target, host, steps, slo_ms, first_response, metrics,
) -> str:
    """Arma el informe en Markdown de una prueba de carga.

    :param target: Perfil, ``local`` o ``render``
    :type target: str
    :param host: Dirección que se midió
    :type host: str
    :param steps: Escalones resumidos
    :type steps: list[dict]
    :param slo_ms: Meta de latencia p95 en milisegundos
    :type slo_ms: float
    :param first_response: Segundos de la primera respuesta, o ``None``
    :type first_response: float or None
    :param metrics: Resultado de :func:`read_metrics`, o ``None``
    :type metrics: dict or None
    :return: Texto Markdown
    :rtype: str
    """
    best = largest_compliant(steps, slo_ms)
    unit = "usuario" if best == 1 else "usuarios"
    verdict = (
        f"Mayor escalón sin errores que cumple la meta de {slo_ms:.0f} ms (SLO): "
        f"{best} {unit}." if best is not None
        else f"Ningún escalón cumple la meta de {slo_ms:.0f} ms (SLO)."
    )
    first = (
        "sin respuesta" if first_response is None
        else f"{first_response:.2f}".replace(".", ",") + " s"
    )
    return "\n".join([
        f"# Prueba de carga: {target}",
        "",
        f"Servicio medido: {host}",
        f"Primera respuesta de `/health`: {first}.",
        "",
        "Latencias en milisegundos de las respuestas 200, medidas desde la máquina "
        "que corre la prueba.",
        "",
        "| Usuarios | Peticiones | Peticiones/s | p50 | p95 | p99 | 200 | 429 | 502 "
        "| Otros errores | Nota |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        *(_row(step, slo_ms) for step in steps),
        "",
        verdict,
        "",
        *_metrics_lines(target, metrics),
        "",
    ])


def stderr_tail(raw: bytes, lines: int = 5) -> str:
    """Las últimas líneas de la salida de error de Locust, para diagnosticar.

    :param raw: Salida de error en bytes
    :type raw: bytes
    :param lines: Cuántas líneas finales se conservan
    :type lines: int
    :return: Las líneas finales como texto, vacío si no hubo salida
    :rtype: str
    """
    return "\n".join(raw.decode("utf-8", errors="replace").splitlines()[-lines:])


def exception_messages(text: str) -> list[str]:
    """Resume las excepciones que Locust registró, sin sus trazas.

    Locust no cuenta como petición lo que falla dentro de una tarea: sin esto, un
    error así deja el escalón en cero sin explicación.

    :param text: Contenido de ``<prefijo>_exceptions.csv``
    :type text: str
    :return: Una línea ``<veces> x <mensaje>`` por excepción distinta
    :rtype: list[str]
    """
    return [
        f"{row['Count']} x {row['Message']}"
        for row in csv.DictReader(io.StringIO(text))
    ]


def _run_step(step: Step, host: str, key: str) -> str:
    """Corre Locust para un escalón y devuelve su CSV de estadísticas.

    :param step: Escalón a correr
    :type step: Step
    :param host: Dirección base del servicio
    :type host: str
    :param key: Clave de cliente; viaja solo por el entorno del proceso
    :type key: str
    :return: Contenido del CSV de estadísticas, vacío si Locust no lo escribió
    :rtype: str
    """
    env = {
        **os.environ, "LOAD_API_KEY": key,
        "LOAD_WAIT_MIN": str(step.wait_min), "LOAD_WAIT_MAX": str(step.wait_max),
    }
    with tempfile.TemporaryDirectory() as folder:
        prefix = str(Path(folder) / "run")
        # Locust termina con 1 si alguna petición falla: no es un error de la prueba
        done = subprocess.run(
            locust_command(step, host, prefix), cwd=ROOT, env=env,
            check=False, capture_output=True,
        )
        stats = Path(f"{prefix}_stats.csv")
        text = stats.read_text(encoding="utf-8") if stats.exists() else ""
        problems = Path(f"{prefix}_exceptions.csv")
        for line in exception_messages(
            problems.read_text(encoding="utf-8") if problems.exists() else ""
        ):
            print(f"Locust registró una excepción: {line}")
        print(f"Escalón de {step.users} usuarios terminado.", flush=True)
        if not text:
            print(f"Locust no dejó estadísticas:\n{stderr_tail(done.stderr)}")
        return text


def _measure(profile: str, host: str, key: str, client) -> str:
    """Corre todos los escalones del perfil y arma el informe.

    :param profile: ``local`` o ``render``
    :type profile: str
    :param host: Dirección base del servicio
    :type host: str
    :param key: Clave de cliente
    :type key: str
    :param client: Cliente HTTP para ``/health`` y ``/metrics``
    :type client: httpx.Client
    :return: Informe en Markdown
    :rtype: str
    """
    first = time_first_response(client, host)
    steps = execute(PROFILES[profile], lambda step: _run_step(step, host, key))
    return render_report(
        profile, host, steps, SLO_MS, first,
        read_metrics_after_limit(client, host, key),
    )


def _inject() -> None:
    """Hace que Python confíe en los certificados del sistema operativo."""
    import truststore  # pylint: disable=import-outside-toplevel
    truststore.inject_into_ssl()


def use_system_certs() -> bool:
    """Usa los certificados del sistema si ``truststore`` está disponible.

    Hace falta en redes que interceptan TLS, donde Python no confía solo.

    :return: ``True`` si se activaron, ``False`` si ``truststore`` no está
    :rtype: bool
    """
    try:
        _inject()
    except ImportError:
        return False
    return True


def _usage() -> int:
    """Imprime el uso y devuelve el código de uso incorrecto."""
    print(
        "Uso: python -m verification.load local\n"
        f"     {KEY_VARIABLE}=<clave> python -m verification.load render <url>"
    )
    return 2


def main(args: list[str]) -> int:
    """Corre la prueba de carga del perfil pedido y guarda el informe.

    :param args: ``local``, o ``render`` y la URL del servicio
    :type args: list[str]
    :return: 0 si se midió y se guardó el informe, 2 si el uso es incorrecto, si
        falta la clave o si Locust no está disponible
    :rtype: int
    """
    profile = args[0] if args else ""
    expected = {"local": 1, "render": 2}.get(profile)
    if expected != len(args):
        return _usage()
    key = os.environ.get(KEY_VARIABLE, "")
    if profile == "render" and not key:
        print(f"Falta la variable {KEY_VARIABLE} con la clave de cliente.")
        return 2
    if importlib.util.find_spec("locust") is None:
        print("Falta Locust: corre con `uv run --with locust python -m "
              "verification.load ...`.")
        return 2
    if profile == "local":
        host = f"http://127.0.0.1:{LOCAL_PORT}"
        with running_product(
            LOCAL_PORT, RATE_LIMIT_PER_MINUTE=str(10**6)
        ) as client:
            report = _measure(profile, host, FACTORY_KEY, client)
    else:
        host = args[1].rstrip("/")
        use_system_certs()
        # Render despierta el servicio dormido en hasta un minuto
        with httpx.Client(timeout=90) as client:
            report = _measure(profile, host, key, client)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / f"load-{profile}.md").write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    random.seed()
    sys.exit(main(sys.argv[1:]))
