"""Unit tests -- `code_agent._tools._ShellCommandRunner` (Stage 3 review fix).

`WorkspaceVerificationRunner` builds commands of the shape
``cd <cwd> && <command>`` -- a real shell is required. `_ShellCommandRunner`
must never leak the spawned process (or its children) when the call is cut
short, whether by its OWN internal timeout or by an external cancellation
(e.g. `ThinRuntime`'s `ToolExecutor`, which wraps every local tool call in a
30s timeout -- see `runtime/thin/executor.py`).
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from swarmline.code_agent import _tools
from swarmline.code_agent._tools import _ShellCommandRunner

pytestmark = pytest.mark.asyncio


async def _wait_until_process_gone(
    pid: int, attempts: int = 200, interval: float = 0.05
) -> None:
    for _ in range(attempts):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        await asyncio.sleep(interval)
    pytest.fail(f"process {pid} was not killed within {attempts * interval:.1f}s")


async def _wait_for_pid_file(pid_file: Path, attempts: int = 100) -> int:
    for _ in range(attempts):
        if pid_file.exists() and pid_file.read_text().strip():
            return int(pid_file.read_text().strip())
        await asyncio.sleep(0.02)
    pytest.fail("child process never started")


class TestNormalCompletion:
    async def test_run_returns_command_result_on_normal_completion(self) -> None:
        runner = _ShellCommandRunner()

        result = await runner.run("printf ok")

        assert result.exit_code == 0
        assert result.stdout == "ok"

    async def test_run_reports_nonzero_exit_code(self) -> None:
        runner = _ShellCommandRunner()

        result = await runner.run("exit 3")

        assert result.exit_code == 3


class TestOwnTimeoutBudget:
    async def test_run_returns_timeout_result_and_kills_process_group(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When `_ShellCommandRunner`'s OWN budget elapses (no external
        cancellation involved), it must return a clean `CommandResult`
        (exit_code=124) -- not raise -- AND the child process the shell
        spawned must actually die, not survive as an orphan."""
        monkeypatch.setattr(_tools, "_VERIFY_COMMAND_TIMEOUT_SECONDS", 0.2)
        pid_file = tmp_path / "child.pid"
        runner = _ShellCommandRunner()

        result = await runner.run(f"sleep 30 & echo $! > {pid_file}; wait")

        assert result.exit_code == 124
        assert "timed out" in result.stderr
        child_pid = await _wait_for_pid_file(pid_file)
        await _wait_until_process_gone(child_pid)


class TestExternalCancellation:
    async def test_run_kills_process_group_and_reraises_cancelled_error(
        self, tmp_path: Path
    ) -> None:
        """An external cancellation (e.g. the surrounding `ToolExecutor`'s
        own 30s per-call timeout) must still kill the WHOLE process group --
        `proc` alone is the shell; `sleep` is its child and would otherwise
        be reparented and orphaned once the shell dies -- and must propagate
        `CancelledError` (swallowing it would violate asyncio's cancellation
        contract)."""
        pid_file = tmp_path / "child.pid"
        runner = _ShellCommandRunner()
        task = asyncio.create_task(runner.run(f"sleep 30 & echo $! > {pid_file}; wait"))
        child_pid = await _wait_for_pid_file(pid_file)

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        await _wait_until_process_gone(child_pid)
