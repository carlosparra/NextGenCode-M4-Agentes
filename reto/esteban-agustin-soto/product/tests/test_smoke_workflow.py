"""Pruebas de ``.github/workflows/smoke.yml``, leído como texto.

No se usa un analizador de YAML (PyYAML no es dependencia del producto): se
revisan líneas y expresiones regulares. Los comentarios se ignoran.
"""

import re
from pathlib import Path

import pytest

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
FORBIDDEN_TRIGGERS = ["push", "pull_request", "workflow_run"]


def code_of(name):
    """Lee un flujo de trabajo y le quita los comentarios.

    :param name: Nombre del archivo dentro de ``.github/workflows``
    :type name: str
    :return: Texto del flujo sin comentarios
    :rtype: str
    """
    text = (WORKFLOWS / name).read_text(encoding="utf-8")
    comment = re.compile(r"\s+#.*$|^\s*#.*$")
    return "\n".join(comment.sub("", line) for line in text.splitlines())


@pytest.fixture(name="smoke_yml")
def smoke_yml_fixture():
    """Texto de ``smoke.yml`` sin comentarios.

    :return: Contenido del flujo de la prueba de humo
    :rtype: str
    """
    return code_of("smoke.yml")


def test_workflow_runs_by_hand_and_on_a_daily_cron(smoke_yml):
    assert re.search(r"^\s+workflow_dispatch\s*:", smoke_yml, re.M)
    assert re.search(r"^\s+schedule\s*:", smoke_yml, re.M)
    assert re.search(r"-\s*cron:\s*[\"']?(\S+ ){4}\S+[\"']?\s*$", smoke_yml, re.M)


def test_workflow_is_not_triggered_by_code_changes(smoke_yml):
    for trigger in FORBIDDEN_TRIGGERS:
        assert not re.search(rf"\b{trigger}\b", smoke_yml), trigger


def test_key_and_url_come_from_github_and_enter_through_env(smoke_yml):
    assert re.search(
        r"^\s+SMOKE_API_KEY:\s*\$\{\{\s*secrets\.SMOKE_API_KEY\s*\}\}\s*$",
        smoke_yml, re.M,
    )
    assert re.search(
        r"^\s+SERVICE_URL:\s*\$\{\{\s*vars\.SERVICE_URL\s*\}\}\s*$", smoke_yml, re.M
    )
    command = [line for line in smoke_yml.splitlines() if "scripts/smoke.py" in line]
    assert command
    assert all("${{" not in line for line in command)
    assert all('"$SERVICE_URL"' in line for line in command)


def test_workflow_has_least_privilege_time_limit_and_concurrency(smoke_yml):
    assert re.search(r"^permissions:\s*\n\s+contents:\s*read\s*$", smoke_yml, re.M)
    assert re.search(r"^\s+timeout-minutes:\s*\d+\s*$", smoke_yml, re.M)
    assert re.search(r"^concurrency:", smoke_yml, re.M)
    assert re.search(r"^\s+cancel-in-progress:\s*false\s*$", smoke_yml, re.M)


def test_workflow_contains_no_written_secret_and_no_tracing(smoke_yml):
    assert not re.search(r"\bset\s+-\w*x", smoke_yml)
    assert "printenv" not in smoke_yml
    assert "echo" not in smoke_yml
    assert not re.search(r"https?://", smoke_yml)
    assert not re.search(r"[A-Za-z0-9_+/=-]{32,}", smoke_yml)


def test_workflow_reuses_the_action_versions_of_ci_and_runs_the_script(smoke_yml):
    ci = code_of("ci.yml")
    for action in ("actions/checkout", "actions/setup-python"):
        pattern = rf"uses:\s*{action}@(\S+)"
        expected = set(re.findall(pattern, ci))
        assert expected
        assert set(re.findall(pattern, smoke_yml)) == expected
    assert "python scripts/smoke.py" in smoke_yml
