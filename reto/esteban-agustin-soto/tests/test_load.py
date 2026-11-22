"""Pruebas de la herramienta de carga, sin Locust ni red."""

import random

import httpx

from verification import load, production

HEADER = (
    "Type,Name,Request Count,Failure Count,Median Response Time,"
    "Average Response Time,Min Response Time,Max Response Time,"
    "Average Content Size,Requests/s,Failures/s,50%,66%,75%,80%,90%,95%,98%,"
    "99%,99.9%,99.99%,100%"
)


def csv_row(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    name, count, failures, rps, p50, p95, p99,
):
    """Una fila de las estadísticas de Locust con las columnas que se leen."""
    return (
        f"POST,{name},{count},{failures},{p50},{p50},1,500,100,{rps},0,"
        f"{p50},{p50},{p50},{p50},{p50},{p95},{p95},{p99},{p99},{p99},{p99}"
    )


def stats_text(*rows):
    """Texto CSV de estadísticas con las filas dadas."""
    return "\n".join([HEADER, *rows]) + "\n"


OK_ONLY = stats_text(
    csv_row("POST /ask [200]", 90, 0, 1.5, 40, 120, 200),
    csv_row("Aggregated", 90, 0, 1.5, 40, 120, 200),
)
WITH_LIMIT = stats_text(
    csv_row("POST /ask [200]", 60, 0, 1.0, 50, 300, 400),
    csv_row("POST /ask [429]", 30, 30, 0.5, 5, 8, 9),
    csv_row("POST /ask [502]", 2, 2, 0.1, 900, 900, 900),
    csv_row("POST /ask [500]", 1, 1, 0.1, 900, 900, 900),
    csv_row("Aggregated", 93, 33, 1.7, 40, 300, 900),
)


def na_row(name):
    """Fila de Locust de un escalón sin peticiones terminadas: todo ``N/A``."""
    return f"POST,{name},0,0,N/A,N/A,N/A,N/A,N/A,0.00,0.00," + ",".join(["N/A"] * 11)


def test_a_step_without_finished_requests_is_read_without_failing():
    rows = load.parse_stats(stats_text(na_row("Aggregated")))
    assert rows["Aggregated"] == {
        "count": 0, "failures": 0, "rps": 0.0, "p50": None, "p95": None,
        "p99": None,
    }
    step = load.summarize_step(1, rows)
    assert (step["requests"], step["ok"], step["p95"]) == (0, 0, None)
    assert not load.meets_slo(step, 2000)
    assert "| 1 | 0 |" in load.render_report(
        "render", "https://x", [{**step, "overflow": False}], 2000, None, None
    )


def test_an_empty_statistics_file_is_an_empty_step():
    step = load.summarize_step(3, load.parse_stats(""))
    assert (step["users"], step["requests"], step["p95"]) == (3, 0, None)


def test_each_status_gets_its_own_request_name():
    assert load.request_name(200) == "POST /ask [200]"
    assert load.request_name(429) == "POST /ask [429]"


def test_stats_are_read_by_request_name():
    rows = load.parse_stats(WITH_LIMIT)
    assert rows["POST /ask [200]"] == {
        "count": 60, "failures": 0, "rps": 1.0, "p50": 50.0, "p95": 300.0,
        "p99": 400.0,
    }
    assert rows["Aggregated"]["count"] == 93


def test_a_step_counts_every_outcome():
    step = load.summarize_step(5, load.parse_stats(WITH_LIMIT))
    assert step["users"] == 5
    assert (step["requests"], step["ok"], step["rate_limited"]) == (93, 60, 30)
    assert (step["unavailable"], step["other_errors"]) == (2, 1)
    assert step["rps"] == 1.7
    assert (step["p50"], step["p95"], step["p99"]) == (50.0, 300.0, 400.0)


def test_a_step_without_successes_has_no_latency():
    only_limit = stats_text(
        csv_row("POST /ask [429]", 10, 10, 0.3, 5, 8, 9),
        csv_row("Aggregated", 10, 10, 0.3, 5, 8, 9),
    )
    step = load.summarize_step(1, load.parse_stats(only_limit))
    assert step["ok"] == 0 and step["p95"] is None


def test_a_step_meets_the_slo_only_without_server_errors():
    clean = load.summarize_step(1, load.parse_stats(OK_ONLY))
    assert load.meets_slo(clean, 2000)
    assert not load.meets_slo(clean, 100)
    dirty = load.summarize_step(1, load.parse_stats(WITH_LIMIT))
    assert not load.meets_slo(dirty, 2000)


def test_rate_limited_answers_do_not_break_the_slo():
    step = {"p95": 300.0, "unavailable": 0, "other_errors": 0, "rate_limited": 9}
    assert load.meets_slo(step, 2000)


def test_the_largest_compliant_step_ignores_the_overflow_step():
    steps = [
        {"users": 1, "p95": 50.0, "unavailable": 0, "other_errors": 0,
         "rate_limited": 0, "overflow": False},
        {"users": 5, "p95": 90.0, "unavailable": 0, "other_errors": 0,
         "rate_limited": 0, "overflow": False},
        {"users": 20, "p95": 5000.0, "unavailable": 0, "other_errors": 0,
         "rate_limited": 0, "overflow": False},
        {"users": 50, "p95": 10.0, "unavailable": 0, "other_errors": 0,
         "rate_limited": 40, "overflow": True},
    ]
    assert load.largest_compliant(steps, 2000) == 5
    assert load.largest_compliant(steps[2:], 2000) is None


def test_the_question_mix_uses_only_made_up_data():
    rng = random.Random(7)
    questions = [load.pick_question(rng) for _ in range(400)]
    assert production.PII_QUESTION in questions
    assert any("EMP-" in question for question in questions)
    assert any("departamento" in question for question in questions)
    personal = [q for q in questions if production.FAKE_CURP in q]
    assert 0.05 < len(personal) / len(questions) < 0.30
    assert all(production.FAKE_EMAIL.endswith("@example.com") for _ in personal)


def test_the_locust_command_does_not_carry_the_key():
    step = load.Step(users=5, seconds=60, wait_min=1.0, wait_max=2.0)
    command = load.locust_command(step, "http://x", "out/prefix")
    assert command[1:3] == ["-m", "locust"]
    for flag in ("--headless", "--only-summary"):
        assert flag in command
    assert command[command.index("-u") + 1] == "5"
    assert command[command.index("-t") + 1] == "60s"
    assert command[command.index("--host") + 1] == "http://x"
    assert command[command.index("--csv") + 1] == "out/prefix"
    assert not any("key" in part.lower() for part in command[3:])


def test_the_profiles_cover_local_and_render():
    local, render = load.PROFILES["local"], load.PROFILES["render"]
    assert [step.users for step in local] == [1, 5, 10, 20, 50, 100]
    assert not any(step.overflow for step in local)
    assert sum(step.overflow for step in render) == 1
    assert render[-1].overflow and render[-1].users > render[-2].users


def test_the_tail_of_locust_errors_is_short_and_readable():
    text = "\n".join(f"line {n}" for n in range(20)).encode()
    tail = load.stderr_tail(text, lines=3)
    assert tail.splitlines() == ["line 17", "line 18", "line 19"]
    assert load.stderr_tail(b"", lines=3) == ""
    assert load.stderr_tail(b"\xff\xfe bad bytes", lines=3) != ""


def test_locust_exceptions_are_summarized_by_message():
    text = (
        "Count,Message,Traceback,Nodes" + "\n" +
        '15,"SSL problem","  File x' + "\n" + '  more",local' + "\n"
    )
    assert load.exception_messages(text) == ["15 x SSL problem"]
    assert load.exception_messages("") == []
    assert load.exception_messages("Count,Message,Traceback,Nodes" + "\n") == []


def test_the_first_response_is_timed_and_never_raises():
    ok = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    assert load.time_first_response(ok, "http://x") >= 0
    def boom(_request):
        raise httpx.ConnectError("down")
    down = httpx.Client(transport=httpx.MockTransport(boom))
    assert load.time_first_response(down, "http://x") is None


def test_the_service_metrics_are_read_with_the_key():
    seen = {}

    def handler(request):
        seen["key"] = request.headers.get("X-API-Key")
        return httpx.Response(200, json={
            "requests": 10, "error_rate": 0.1, "pid": 1, "tokens": {},
            "latency_ms": {"p50": 5, "p95": 9}, "cost_usd": 0.2,
            "slo": {"p95_ms_target": 2000, "met": True},
        })

    client = httpx.Client(transport=httpx.MockTransport(handler))
    metrics = load.read_metrics(client, "http://x", "k")
    assert seen["key"] == "k"
    assert metrics == {
        "requests": 10, "error_rate": 0.1, "p95_ms": 9, "cost_usd": 0.2,
        "slo_met": True,
    }
    denied = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401)))
    assert load.read_metrics(denied, "http://x", "bad") is None


def metrics_client(statuses):
    """Cliente cuyo ``/metrics`` responde con los códigos dados, en orden."""
    pending = list(statuses)
    body = {
        "requests": 1, "error_rate": 0, "pid": 1, "tokens": {},
        "latency_ms": {"p50": 1, "p95": 2}, "cost_usd": 0.0,
        "slo": {"p95_ms_target": 2000, "met": True},
    }

    def handler(_request):
        code = pending.pop(0)
        return httpx.Response(code, json=body if code == 200 else {"detail": "x"})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_metrics_are_read_at_once_when_the_limit_is_not_exhausted():
    waits = []
    metrics = load.read_metrics_after_limit(
        metrics_client([200]), "http://x", "k", sleep=waits.append
    )
    assert metrics["requests"] == 1 and not waits


def test_metrics_wait_one_window_when_the_limit_was_exhausted():
    waits = []
    metrics = load.read_metrics_after_limit(
        metrics_client([429, 200]), "http://x", "k", sleep=waits.append
    )
    assert metrics["requests"] == 1
    assert waits == [load.RETRY_SECONDS] and load.RETRY_SECONDS >= 60


def test_metrics_give_up_after_one_retry():
    waits = []
    metrics = load.read_metrics_after_limit(
        metrics_client([429, 429]), "http://x", "k", sleep=waits.append
    )
    assert metrics is None and len(waits) == 1


def test_execute_runs_every_step_and_collects_them():
    profile = [
        load.Step(users=1, seconds=1, wait_min=0, wait_max=0),
        load.Step(users=3, seconds=1, wait_min=0, wait_max=0, overflow=True),
    ]
    ran = []

    def runner(step):
        ran.append(step.users)
        return OK_ONLY

    steps = load.execute(profile, runner)
    assert ran == [1, 3]
    assert [step["users"] for step in steps] == [1, 3]
    assert [step["overflow"] for step in steps] == [False, True]


def test_the_report_has_a_row_per_step_and_the_conclusion():
    clean = load.summarize_step(1, load.parse_stats(OK_ONLY))
    clean["overflow"] = False
    limited = load.summarize_step(10, load.parse_stats(WITH_LIMIT))
    limited["overflow"] = True
    text = load.render_report(
        "local", "http://127.0.0.1:1", [clean, limited], 2000,
        first_response=1.25,
        metrics={"requests": 93, "error_rate": 0.1, "p95_ms": 9,
                 "cost_usd": 0.0, "slo_met": True},
    )
    assert text.count("\n| 1 |") == 1 and text.count("\n| 10 |") == 1
    assert "1,25" in text
    assert "1 usuarios" in text or "1 usuario" in text
    assert "SLO" in text and "2000" in text
    assert "(límite)" in text
    assert "modelo simulado" in text
    real = load.render_report(
        "render", "https://x", [clean], 2000, None,
        {"requests": 1, "error_rate": 0, "p95_ms": 1, "cost_usd": 0.1,
         "slo_met": True},
    )
    assert "modelo simulado" not in real


def test_the_report_never_contains_a_key():
    text = load.render_report("render", "https://x.onrender.com", [], 2000, None, None)
    assert "X-API-Key" not in text and "SMOKE_API_KEY" not in text


def test_the_render_profile_needs_the_key_in_the_environment(monkeypatch, capsys):
    monkeypatch.delenv("SMOKE_API_KEY", raising=False)
    assert load.main(["render", "https://x.onrender.com"]) == 2
    assert "SMOKE_API_KEY" in capsys.readouterr().out


def test_an_unknown_profile_shows_the_usage(capsys):
    assert load.main(["nope"]) == 2
    assert "local" in capsys.readouterr().out
    assert load.main([]) == 2


def test_the_system_certificates_are_optional(monkeypatch):
    monkeypatch.setattr(load, "_inject", lambda: (_ for _ in ()).throw(ImportError()))
    assert load.use_system_certs() is False
    monkeypatch.setattr(load, "_inject", lambda: None)
    assert load.use_system_certs() is True
