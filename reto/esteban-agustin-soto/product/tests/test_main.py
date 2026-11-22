"""Unit tests for app.main and the web page."""

from pathlib import Path

from conftest import ScriptedModel, answer_json

INDEX = Path(__file__).resolve().parents[1] / "app" / "static" / "index.html"


def test_injected_model_is_used_and_api_keeps_no_state(make_client):
    model = ScriptedModel([answer_json("injected")])
    client = make_client(model=model)
    history = [{"role": "user", "content": "before"}]
    first = client.post("/ask", json={"question": "one", "history": history})
    assert first.json()["answer"] == "injected"
    assert set(first.json()) == {
        "answer", "steps", "tools_used", "input_tokens", "output_tokens",
        "request_id", "model", "route", "cached_calls", "cost_usd",
    }
    assert isinstance(first.json()["request_id"], str)
    assert first.json()["request_id"]
    client.post("/ask", json={"question": "two"})
    assert "before" in [m["content"] for m in model.calls[0]]
    assert "before" not in [m["content"] for m in model.calls[1]]


def test_page_has_test_ids_and_never_uses_inner_html(make_client):
    response = make_client().get("/")
    assert response.status_code == 200
    for test_id in ("question", "send", "answer"):
        assert f'data-testid="{test_id}"' in response.text
    assert "innerHTML" not in INDEX.read_text(encoding="utf-8")
