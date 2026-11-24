"""El servidor MCP real por stdio, como lo arranca un host (Claude Code, VS Code)."""

import os
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters

from tests.conftest import run

ROOT = Path(__file__).resolve().parent.parent


def test_stdio_server_answers_a_host():
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.mcp_server"],
        cwd=str(ROOT),
        env={**os.environ, "MODEL_PROVIDER": "fake", "LANGSMITH_TRACING": "false"},
    )

    async def flow():
        async with Client(params) as client:
            names = [tool.name for tool in (await client.list_tools()).tools]
            result = await client.call_tool(
                "vacation_balance", {"employee_id": "EMP-0001"}
            )
            return names, result

    names, result = run(flow())
    assert sorted(names) == ["ask_hr", "department_summary", "vacation_balance"]
    assert result.structured_content["balance_days"] >= 0
    assert result.structured_content["name"] == "Ana López"
