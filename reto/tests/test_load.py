"""Pruebas de la prueba de carga, con un servidor simulado (sin red)."""

import asyncio

import httpx

from verification import load


def fake_service(status=200):
    def handler(request):
        assert request.headers["X-API-Key"] == "good-key"
        return httpx.Response(status, json={"answer": "ok"})

    return httpx.MockTransport(handler)


def test_percentile_uses_the_nearest_rank():
    assert load.percentile([10, 20, 30, 40], 0.5) == 20
    assert load.percentile([10, 20, 30, 40], 0.95) == 40


def test_fire_sends_every_request_with_the_key():
    results = asyncio.run(load.fire("https://x", "good-key", 12, 4, fake_service()))
    assert [code for code, _ in results] == [200] * 12


def test_a_healthy_run_passes():
    summary = load.summarize([(200, 100.0)] * 20, p95_target_ms=500)
    assert summary["passed"]
    assert summary["ok"] == 20


def test_server_errors_fail_the_run():
    results = [(200, 100.0)] * 19 + [(502, 100.0)]
    assert not load.summarize(results, p95_target_ms=500)["passed"]


def test_too_many_rejections_fail_the_run():
    results = [(200, 100.0)] * 18 + [(429, 5.0)] * 2
    assert not load.summarize(results, p95_target_ms=500)["passed"]


def test_a_slow_p95_fails_the_run():
    assert not load.summarize([(200, 900.0)] * 20, p95_target_ms=500)["passed"]


def test_remote_runs_need_the_key_from_the_environment(monkeypatch, capsys):
    monkeypatch.delenv("SMOKE_API_KEY", raising=False)
    assert load.main(["https://x"]) == 2
    assert "SMOKE_API_KEY" in capsys.readouterr().out


def test_remote_run_reports_and_decides(monkeypatch, capsys):
    monkeypatch.setenv("SMOKE_API_KEY", "good-key")
    monkeypatch.setenv("LOAD_REQUESTS", "6")

    async def fake_fire(url, key, total, _concurrency):
        assert (url, key, total) == ("https://x", "good-key", 6)
        return [(200, 50.0)] * total

    monkeypatch.setattr(load, "fire", fake_fire)
    assert load.main(["https://x/"]) == 0
    assert "requests=6" in capsys.readouterr().out
