from __future__ import annotations

import os
import subprocess
import sys

import pytest
from mcp import Client, StdioServerParameters

pytestmark = pytest.mark.anyio

# Nothing listens on port 9, so calls to Milton fail fast and the bundled model list is used.
UNREACHABLE = "http://127.0.0.1:9"


def env(**extra: str) -> dict[str, str]:
    base = {k: v for k, v in os.environ.items() if not k.startswith("MILTON_")}
    return {**base, "MILTON_BASE_URL": UNREACHABLE, **extra}


def test_stdio_without_a_key_exits_with_instructions():
    proc = subprocess.run(
        [sys.executable, "-m", "milton_mcp"], env=env(), capture_output=True, text=True, timeout=30, check=False
    )
    assert proc.returncode != 0
    assert "set MILTON_API_KEY" in proc.stderr


async def test_stdio_serves_tools_over_a_real_subprocess():
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "milton_mcp"], env=env(MILTON_API_KEY="mlt_" + "a" * 52)
    )
    async with Client(params, cache=None) as client:
        tools = await client.list_tools()
        result = await client.call_tool("milton_macro_analysis", {"model": "claude-opus-5-5"})
    assert "milton_technical_analysis" in {t.name for t in tools.tools}
    assert result.is_error is True
    assert f"Couldn't reach Milton at {UNREACHABLE}" in result.content[0].text
