"""Pruebas de las trazas opcionales de LangSmith, sin red."""

import sys

from conftest import RecordingTracer, build_client, langsmith_settings

from app.config import load_settings
from app.tracing import NoopTracer, build_tracer


def test_tracing_is_off_without_an_api_key(employees_file, monkeypatch):
    monkeypatch.setitem(sys.modules, "langsmith", None)
    settings = load_settings(
        {"EMPLOYEES_PATH": str(employees_file), "LANGSMITH_TRACING": "true"}
    )

    tracer = build_tracer(settings)

    assert isinstance(tracer, NoopTracer)

    def answer():
        return 42

    assert tracer.trace(answer, name="agent_run", request_id="r-1") is answer


def test_langsmith_tracer_hides_content_and_tags_the_request_id(
    employees_file, monkeypatch
):
    recorded = {}
    settings = langsmith_settings(employees_file, monkeypatch, recorded)

    traced = build_tracer(settings).trace(
        lambda: 42, name="agent_run", request_id="r-7"
    )

    assert traced() == 42
    assert recorded["client"]["hide_inputs"] is True
    assert recorded["client"]["hide_outputs"] is True
    assert recorded["traceable"][0]["metadata"] == {"request_id": "r-7"}


def test_agent_run_model_calls_and_tools_are_traced_with_the_request_id(
    settings, fake_llm, directory, clock, log_stream
):
    tracer = RecordingTracer()
    client = build_client(
        settings,
        fake_llm,
        directory,
        clock=clock,
        log_stream=log_stream,
        tracer=tracer,
    )

    client.post(
        "/ask",
        json={"question": "¿Quién es EMP-0004?"},
        headers={"X-Request-ID": "trace-1"},
    )

    names = {span["name"] for span in tracer.spans}
    assert {"agent_run", "llm", "tool"} <= names
    assert {span["request_id"] for span in tracer.spans} == {"trace-1"}
