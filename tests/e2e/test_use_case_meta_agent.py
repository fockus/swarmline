"""UC5: Meta Agent (Code Execution) -- Execute analysis scripts, handle timeouts
and syntax errors via exec_code.

Headless E2E test: validates subprocess execution, output capture, timeout
handling, and error reporting without any LLM calls.
"""

from __future__ import annotations

from cognitia.mcp._tools_code import exec_code


async def test_exec_valid_arithmetic():
    """Simple arithmetic prints correct result."""
    res = await exec_code(trusted=True, code="print(sum(range(100)))")
    assert res["ok"] is True
    assert res["data"]["stdout"] == "4950"
    assert res["data"]["returncode"] == 0


async def test_exec_stdlib_import():
    """Code using stdlib (os.path) executes correctly."""
    res = await exec_code(trusted=True, code="import os; print(os.path.exists('/'))")
    assert res["ok"] is True
    assert res["data"]["stdout"] == "True"


async def test_exec_timeout_kills_long_running():
    """Long-running code is killed after timeout."""
    res = await exec_code(trusted=True, code="import time; time.sleep(100)", timeout_seconds=2)
    assert res["ok"] is False
    assert "timed out" in res["error"].lower() or res["data"].get("timeout") is True


async def test_exec_syntax_error_returns_error():
    """Syntax errors are reported, not swallowed."""
    res = await exec_code(trusted=True, code="def (")
    assert res["ok"] is False
    assert res["data"]["returncode"] != 0
    assert "SyntaxError" in res["data"]["stderr"] or "SyntaxError" in res.get("error", "")


async def test_exec_multiline_computation():
    """Multi-line code with computation returns correct output."""
    code = "\n".join([
        "data = [i ** 2 for i in range(10)]",
        "total = sum(data)",
        "print(f'squares_sum={total}')",
    ])
    res = await exec_code(trusted=True, code=code)
    assert res["ok"] is True
    assert "squares_sum=285" in res["data"]["stdout"]


async def test_exec_stderr_captured():
    """Stderr output is captured separately from stdout."""
    code = "import sys; print('out'); print('err', file=sys.stderr)"
    res = await exec_code(trusted=True, code=code)
    assert res["ok"] is True
    assert res["data"]["stdout"] == "out"
    assert "err" in res["data"]["stderr"]


async def test_exec_nonzero_exit_code():
    """Non-zero exit via sys.exit is reported as failure."""
    res = await exec_code(trusted=True, code="import sys; sys.exit(42)")
    assert res["ok"] is False
    assert res["data"]["returncode"] == 42
