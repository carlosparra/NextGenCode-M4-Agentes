"""Pruebas del hook de permisos: cada agente escribe solo en sus carpetas."""

import json
import subprocess
import sys

import pytest

from hooks.permissions import ROOT, check


def write(agent, path, tool="Write"):
    return {"agent_type": agent, "tool_name": tool, "tool_input": {"file_path": path}}


@pytest.mark.parametrize(
    "agent, path",
    [
        ("architect", "output/plan.md"),
        ("architect", "product/doc/adr/0001-stateless-api.md"),
        ("qa-unit", "product/tests/test_agent.py"),
        ("developer", "product/app/main.py"),
        ("developer", "product/requirements.txt"),
    ],
)
def test_agent_can_write_in_its_folders(agent, path):
    assert check(write(agent, path)) is None


def test_developer_cannot_write_tests():
    reason = check(write("developer", "product/tests/test_agent.py"))
    assert "developer no puede escribir product/tests/test_agent.py" in reason


def test_qa_unit_cannot_write_code():
    assert check(write("qa-unit", "product/app/main.py", tool="Edit")) is not None


def test_absolute_paths_are_checked_too():
    assert check(write("developer", str(ROOT / "product/app/main.py"))) is None
    assert check(write("developer", str(ROOT / "hooks/permissions.py"))) is not None


def test_paths_outside_the_project_are_blocked():
    assert "no puede escribir" in check(write("developer", "product/app/../../../x"))


def test_reading_and_the_orchestrator_are_not_restricted():
    assert check({"agent_type": "developer", "tool_name": "Read"}) is None
    assert check(write(None, "product/app/main.py")) is None


@pytest.mark.parametrize("agent, code", [("developer", 0), ("qa-unit", 2)])
def test_hook_exit_code_tells_claude_code_what_to_do(agent, code):
    event = json.dumps(write(agent, "product/app/main.py"))
    hook = subprocess.run(
        [sys.executable, str(ROOT / "hooks/permissions.py")],
        input=event,
        capture_output=True,
        text=True,
        check=False,
    )
    assert hook.returncode == code
