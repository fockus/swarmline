"""Tests for MCP code execution tool.

All tests use real subprocess execution (no mocks).
"""

from __future__ import annotations

import pytest

from cognitia.mcp._tools_code import exec_code


class TestExecCode:
    """Tests for exec_code function."""

    @pytest.mark.asyncio
    async def test_exec_simple_arithmetic_returns_stdout(self) -> None:
        result = await exec_code("print(2 + 2)", trusted=True)
        assert result["ok"] is True
        assert result["data"]["stdout"] == "4"
        assert result["data"]["returncode"] == 0

    @pytest.mark.asyncio
    async def test_exec_json_output_valid(self) -> None:
        import json

        result = await exec_code("import json; print(json.dumps({'ok': True}))", trusted=True)
        assert result["ok"] is True
        parsed = json.loads(result["data"]["stdout"])
        assert parsed == {"ok": True}

    @pytest.mark.asyncio
    async def test_exec_syntax_error_returns_failure(self) -> None:
        result = await exec_code("def (invalid", trusted=True)
        assert result["ok"] is False
        assert result["data"]["returncode"] != 0
        assert "SyntaxError" in result["data"]["stderr"]

    @pytest.mark.asyncio
    async def test_exec_timeout_kills_process(self) -> None:
        result = await exec_code("import time; time.sleep(60)", timeout_seconds=1, trusted=True)
        assert result["ok"] is False
        assert "timed out" in result["error"]
        assert result["data"]["timeout"] is True

    @pytest.mark.asyncio
    async def test_exec_empty_code_succeeds(self) -> None:
        result = await exec_code("", trusted=True)
        assert result["ok"] is True
        assert result["data"]["stdout"] == ""
        assert result["data"]["returncode"] == 0

    @pytest.mark.asyncio
    async def test_exec_stderr_captured(self) -> None:
        result = await exec_code("import sys; print('err', file=sys.stderr)", trusted=True)
        assert result["ok"] is True
        assert result["data"]["stderr"] == "err"

    @pytest.mark.asyncio
    async def test_exec_runtime_error_returns_failure(self) -> None:
        result = await exec_code("raise ValueError('boom')", trusted=True)
        assert result["ok"] is False
        assert "ValueError" in result["error"]
        assert result["data"]["returncode"] != 0

    @pytest.mark.asyncio
    async def test_exec_multiline_output(self) -> None:
        result = await exec_code("for i in range(3): print(i)", trusted=True)
        assert result["ok"] is True
        assert result["data"]["stdout"] == "0\n1\n2"
