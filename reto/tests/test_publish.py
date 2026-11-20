"""Pruebas del script de publicación, sin tocar GitHub."""

import subprocess

from scripts import publish


def ready(tmp_path, monkeypatch, approved=True):
    product = tmp_path / "product"
    product.mkdir()
    (product / ".gitignore").write_text(".env\n", encoding="utf-8")
    (product / "render.yaml").write_text("services: []\n", encoding="utf-8")
    approval = tmp_path / "approved.txt"
    if approved:
        approval.write_text("Aprobado por la persona", encoding="utf-8")
    monkeypatch.setattr(publish, "PRODUCT", product)
    monkeypatch.setattr(publish, "APPROVAL", approval)
    monkeypatch.setattr(publish, "STAGE", tmp_path / "stage")
    return product


def test_nothing_is_published_without_approval(tmp_path, monkeypatch, capsys):
    ready(tmp_path, monkeypatch, approved=False)
    assert publish.main(["hr-assistant"]) == 1
    assert "falta la aprobación" in capsys.readouterr().out


def test_the_product_must_ignore_env(tmp_path, monkeypatch):
    product = ready(tmp_path, monkeypatch)
    (product / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    assert "product/.gitignore debe excluir .env" in publish.problems()


def test_first_publication_creates_a_private_repository():
    first = publish.commands("hr-assistant", first_time=True)
    assert first[0] == ["git", "init", "-b", "main"]
    assert first[-1][:4] == ["gh", "repo", "create", "hr-assistant"]
    assert "--private" in first[-1]


def test_later_publications_just_push():
    assert publish.commands("hr-assistant", first_time=False)[-1] == ["git", "push"]


def test_publish_runs_each_command_in_a_copy(tmp_path, monkeypatch, capsys):
    ready(tmp_path, monkeypatch)
    calls = []

    def fake_run(command, cwd, check):
        calls.append((command, cwd, check))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(publish.subprocess, "run", fake_run)
    assert publish.main(["hr-assistant"]) == 0
    assert all(cwd == tmp_path / "stage" for _, cwd, _ in calls)
    assert (tmp_path / "stage" / "render.yaml").exists()
    assert "[OK] publish" in capsys.readouterr().out


def test_stage_keeps_the_product_repository_and_never_copies_env(
    tmp_path, monkeypatch
):
    product = ready(tmp_path, monkeypatch)
    (product / ".env").write_text("SECRET=1\n", encoding="utf-8")
    stage = tmp_path / "stage"
    (stage / ".git").mkdir(parents=True)
    (stage / "old.txt").write_text("x", encoding="utf-8")
    publish.stage()
    assert (stage / ".git").is_dir()
    assert not (stage / "old.txt").exists()
    assert not (stage / ".env").exists()
    assert (stage / "render.yaml").exists()


def test_usage_needs_the_repository_name():
    assert publish.main([]) == 2
