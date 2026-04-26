"""Integration tests for CliAgentRuntime — subprocess-based CLI runtime.

Tests validate the full flow: mock subprocess -> NDJSON stdout -> RuntimeEvent stream.
Subprocess is mocked (external process = legitimate mock target).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarmline.runtime.cli.runtime import CliAgentRuntime
from swarmline.runtime.cli.types import CliConfig
from swarmline.runtime.registry import get_default_registry
from swarmline.runtime.types import Message, RuntimeConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ndjson_lines(*dicts: dict) -> list[bytes]:
    """Encode dicts as NDJSON byte lines (each terminated with newline)."""
    return [json.dumps(d).encode() + b"\n" for d in dicts]


def _make_mock_process(
    stdout_lines: list[bytes],
    returncode: int = 0,
    stderr_data: bytes = b"",
) -> MagicMock:
    """Create a mock asyncio.subprocess.Process with async stdout iteration."""
    proc = MagicMock()

    # stdout — async iterable over lines
    async def _stdout_iter():
        for line in stdout_lines:
            yield line

    proc.stdout = _stdout_iter()

    # stdin
    stdin = MagicMock()
    stdin.write = MagicMock()
    stdin.drain = AsyncMock()
    stdin.close = MagicMock()
    proc.stdin = stdin

    # stderr
    stderr_mock = AsyncMock()
    stderr_mock.read = AsyncMock(return_value=stderr_data)
    proc.stderr = stderr_mock

    # returncode — initially None (running), then set after wait()
    proc.returncode = None

    async def _wait():
        proc.returncode = returncode

    proc.wait = AsyncMock(side_effect=_wait)
    proc.terminate = MagicMock()
    proc.kill = MagicMock()

    return proc


def _runtime_config() -> RuntimeConfig:
    return RuntimeConfig(runtime_name="cli")


def _cli_config() -> CliConfig:
    return CliConfig(
        command=[
            "claude",
            "--print",
            "--verbose",
            "--output-format",
            "stream-json",
            "-",
        ]
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCliRuntimeFullConversationFlow:
    """test_cli_runtime_full_conversation_flow:
    Mock process emits assistant text, tool_use, and result NDJSON lines.
    Verify run() yields correct RuntimeEvent type sequence.
    """

    async def test_cli_runtime_run_multiple_ndjson_events_yields_correct_event_types(
        self,
    ):
        # Arrange
        stdout_lines = _make_ndjson_lines(
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "text", "text": "Thinking about it..."}]
                },
            },
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "read_file",
                            "input": {"path": "/tmp/x.py"},
                        }
                    ]
                },
            },
            {"type": "result", "result": "Done! File contents are here."},
        )
        mock_proc = _make_mock_process(stdout_lines, returncode=0)

        rt = CliAgentRuntime(config=_runtime_config(), cli_config=_cli_config())
        messages = [Message(role="user", content="Read that file")]

        # Act
        events = []
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
            async for ev in rt.run(
                messages=messages,
                system_prompt="You are helpful.",
                active_tools=[],
            ):
                events.append(ev)

        # Assert
        assert len(events) == 3
        assert events[0].type == "assistant_delta"
        assert events[0].data["text"] == "Thinking about it..."
        assert events[1].type == "tool_call_started"
        assert events[1].data["name"] == "read_file"
        assert events[1].data["args"] == {"path": "/tmp/x.py"}
        assert events[2].type == "final"
        assert events[2].data["text"] == "Done! File contents are here."


class TestCliRuntimeErrorRecovery:
    """test_cli_runtime_error_recovery:
    Process emits valid events then exits with code 1.
    Verify runtime yields parsed events + a trailing error event.
    """

    async def test_cli_runtime_process_exit_code_1_yields_events_then_error(self):
        # Arrange
        stdout_lines = _make_ndjson_lines(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "Starting..."}]},
            },
            {"type": "result", "result": "Partial answer"},
        )
        stderr_bytes = b"segfault in tool executor"
        mock_proc = _make_mock_process(
            stdout_lines, returncode=1, stderr_data=stderr_bytes
        )

        rt = CliAgentRuntime(config=_runtime_config(), cli_config=_cli_config())
        messages = [Message(role="user", content="Do something")]

        # Act
        events = []
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
            async for ev in rt.run(
                messages=messages,
                system_prompt="",
                active_tools=[],
            ):
                events.append(ev)

        # Assert — parsed events come first, then error
        assert len(events) == 3
        assert events[0].type == "assistant_delta"
        assert events[0].data["text"] == "Starting..."
        assert events[1].type == "final"
        assert events[2].type == "error"
        assert events[2].data["kind"] == "runtime_crash"
        assert "segfault" in events[2].data["message"]
        assert (
            "exit" in events[2].data["message"].lower()
            or "1" in events[2].data["message"]
        )


class TestCliRuntimeContextManagerCleanup:
    """test_cli_runtime_context_manager_cleanup:
    async with CliAgentRuntime() — verify cleanup is called on exit.
    """

    async def test_cli_runtime_async_context_manager_calls_cleanup_on_exit(self):
        # Arrange
        rt = CliAgentRuntime(config=_runtime_config(), cli_config=_cli_config())

        # Act
        with patch.object(rt, "cleanup", new_callable=AsyncMock) as mock_cleanup:
            async with rt:
                pass  # just enter and exit

        # Assert
        mock_cleanup.assert_awaited_once()

    async def test_cli_runtime_async_context_manager_calls_cleanup_on_exception(self):
        # Arrange
        rt = CliAgentRuntime(config=_runtime_config(), cli_config=_cli_config())

        # Act
        with patch.object(rt, "cleanup", new_callable=AsyncMock) as mock_cleanup:
            with pytest.raises(ValueError, match="boom"):
                async with rt:
                    raise ValueError("boom")

        # Assert — cleanup still called even after exception
        mock_cleanup.assert_awaited_once()


class TestCliRuntimeTimeout:
    """Process exceeds timeout -> error event with mcp_timeout kind."""

    async def test_cli_runtime_run_timeout_yields_timeout_error_event(self):
        # Arrange — subprocess that never finishes
        async def _stuck_stdout():
            import asyncio

            await asyncio.sleep(999)
            yield b""  # pragma: no cover

        mock_proc = MagicMock()
        mock_proc.stdout = _stuck_stdout()
        stdin = MagicMock()
        stdin.write = MagicMock()
        stdin.drain = AsyncMock()
        stdin.close = MagicMock()
        mock_proc.stdin = stdin
        mock_proc.stderr = AsyncMock()
        mock_proc.returncode = None
        mock_proc.terminate = MagicMock()
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        cli_config = CliConfig(command=["claude", "--print", "-"], timeout_seconds=0.1)
        rt = CliAgentRuntime(config=_runtime_config(), cli_config=cli_config)

        # Act
        events = []
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
            async for ev in rt.run(
                messages=[Message(role="user", content="hi")],
                system_prompt="",
                active_tools=[],
            ):
                events.append(ev)

        # Assert
        error_events = [e for e in events if e.type == "error"]
        assert len(error_events) == 1
        assert error_events[0].data["kind"] == "mcp_timeout"
        assert "timed out" in error_events[0].data["message"]


class TestCliRuntimeRegisteredInRegistry:
    """CLI runtime is registered in RuntimeRegistry as 'cli'."""

    def test_cli_runtime_registered_in_registry(self):
        registry = get_default_registry()
        assert registry.is_registered("cli")


class TestCliRuntimeTerminalContract:
    """Cli runtime must emit a terminal event on every completed run."""

    async def test_cli_runtime_clean_exit_without_final_yields_bad_model_output(self):
        stdout_lines = _make_ndjson_lines({"step": "processing"})
        mock_proc = _make_mock_process(stdout_lines, returncode=0)

        rt = CliAgentRuntime(
            config=_runtime_config(),
            cli_config=CliConfig(command=["my-agent", "--json"]),
        )

        events = []
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
            async for ev in rt.run(
                messages=[Message(role="user", content="hi")],
                system_prompt="",
                active_tools=[],
            ):
                events.append(ev)

        assert events[-1].type == "error"
        assert events[-1].data["kind"] == "bad_model_output"
        assert "without a final" in events[-1].data["message"]
