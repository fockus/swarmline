"""Unit tests for CliAgentRuntime."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from swarmline.runtime.cli.parser import ClaudeNdjsonParser, GenericNdjsonParser, PiRpcParser
from swarmline.runtime.cli.types import CliConfig
from swarmline.runtime.types import Message, RuntimeConfig


class TestCliRuntimeParserSelection:
    """CliAgentRuntime selects parser based on command."""

    def test_cli_runtime_default_parser_claude_command(self) -> None:
        """Command starting with 'claude' -> ClaudeNdjsonParser."""
        from swarmline.runtime.cli.runtime import CliAgentRuntime

        config = RuntimeConfig(runtime_name="cli")
        cli_config = CliConfig(command=["claude", "--print", "-"])
        rt = CliAgentRuntime(config=config, cli_config=cli_config)
        assert isinstance(rt._parser, ClaudeNdjsonParser)

    def test_cli_runtime_default_parser_custom_command(self) -> None:
        """Command not starting with 'claude' -> GenericNdjsonParser."""
        from swarmline.runtime.cli.runtime import CliAgentRuntime

        config = RuntimeConfig(runtime_name="cli")
        cli_config = CliConfig(command=["my-agent", "--json"])
        rt = CliAgentRuntime(config=config, cli_config=cli_config)
        assert isinstance(rt._parser, GenericNdjsonParser)

    def test_cli_runtime_default_parser_pi_rpc_preset(self) -> None:
        """PI RPC preset selects PiRpcParser."""
        from swarmline.runtime.cli.runtime import CliAgentRuntime

        config = RuntimeConfig(runtime_name="cli")
        rt = CliAgentRuntime(config=config, cli_config=CliConfig.pi())
        assert isinstance(rt._parser, PiRpcParser)

    def test_cli_runtime_explicit_parser_overrides_auto(self) -> None:
        """Explicitly provided parser takes precedence."""
        from swarmline.runtime.cli.runtime import CliAgentRuntime

        config = RuntimeConfig(runtime_name="cli")
        cli_config = CliConfig(command=["claude", "--print", "-"])
        parser = GenericNdjsonParser()
        rt = CliAgentRuntime(config=config, cli_config=cli_config, parser=parser)
        assert rt._parser is parser

    def test_cli_runtime_default_parser_absolute_claude_path(self) -> None:
        """Absolute path to claude should still use ClaudeNdjsonParser."""
        from swarmline.runtime.cli.runtime import CliAgentRuntime

        config = RuntimeConfig(runtime_name="cli")
        cli_config = CliConfig(command=["/usr/local/bin/claude", "--print", "-"])
        rt = CliAgentRuntime(config=config, cli_config=cli_config)
        assert isinstance(rt._parser, ClaudeNdjsonParser)


class TestCliRuntimeCommandNormalization:
    """Claude CLI commands are normalized to the NDJSON-compatible shape."""

    def test_legacy_claude_command_gets_output_format_and_verbose(self) -> None:
        from swarmline.runtime.cli.runtime import _normalize_claude_command

        assert _normalize_claude_command(["claude", "--print", "-"], "stream-json") == [
            "claude",
            "--print",
            "--output-format",
            "stream-json",
            "--verbose",
            "-",
        ]

    def test_legacy_output_flag_is_upgraded(self) -> None:
        from swarmline.runtime.cli.runtime import _normalize_claude_command

        assert _normalize_claude_command(
            ["claude", "--print", "--output", "stream-json", "-"],
            "stream-json",
        ) == [
            "claude",
            "--print",
            "--output-format",
            "stream-json",
            "--verbose",
            "-",
        ]

    def test_non_claude_command_is_left_untouched(self) -> None:
        from swarmline.runtime.cli.runtime import _normalize_claude_command

        assert _normalize_claude_command(["my-agent", "--json"], "json") == [
            "my-agent",
            "--json",
        ]


class TestCliRuntimeProtocol:
    """CliAgentRuntime satisfies AgentRuntime protocol."""

    def test_cli_runtime_has_run_method(self) -> None:
        """CliAgentRuntime has async run method."""
        from swarmline.runtime.cli.runtime import CliAgentRuntime

        config = RuntimeConfig(runtime_name="cli")
        rt = CliAgentRuntime(config=config)
        assert hasattr(rt, "run")
        assert asyncio.iscoroutinefunction(rt.cleanup)

    def test_cli_runtime_has_cancel_method(self) -> None:
        """CliAgentRuntime has cancel method."""
        from swarmline.runtime.cli.runtime import CliAgentRuntime

        config = RuntimeConfig(runtime_name="cli")
        rt = CliAgentRuntime(config=config)
        assert hasattr(rt, "cancel")
        assert callable(rt.cancel)

    def test_cli_runtime_has_cleanup_method(self) -> None:
        """CliAgentRuntime has async cleanup method."""
        from swarmline.runtime.cli.runtime import CliAgentRuntime

        config = RuntimeConfig(runtime_name="cli")
        rt = CliAgentRuntime(config=config)
        assert hasattr(rt, "cleanup")
        assert asyncio.iscoroutinefunction(rt.cleanup)

    def test_cli_runtime_isinstance_agent_runtime(self) -> None:
        """CliAgentRuntime passes isinstance check for AgentRuntime."""
        from swarmline.runtime.base import AgentRuntime
        from swarmline.runtime.cli.runtime import CliAgentRuntime

        config = RuntimeConfig(runtime_name="cli")
        rt = CliAgentRuntime(config=config)
        assert isinstance(rt, AgentRuntime)


class TestCliRuntimePromptSerialization:
    """CliAgentRuntime serializes stdin payload deterministically."""

    def test_build_stdin_payload_includes_system_prompt_and_conversation(self) -> None:
        from swarmline.runtime.cli.runtime import _build_stdin_payload

        payload = _build_stdin_payload(
            messages=[
                Message(role="user", content="hello"),
                Message(role="assistant", content="world"),
            ],
            system_prompt="be helpful",
        )

        assert payload == (
            "System instructions:\nbe helpful\n\n"
            "Conversation:\nuser: hello\nassistant: world"
        )

    def test_build_stdin_payload_omits_empty_system_prompt(self) -> None:
        from swarmline.runtime.cli.runtime import _build_stdin_payload

        payload = _build_stdin_payload(
            messages=[Message(role="user", content="hello")],
            system_prompt="  ",
        )

        assert payload == "Conversation:\nuser: hello"

    def test_build_cli_input_payload_pi_rpc_wraps_prompt_command(self) -> None:
        from swarmline.runtime.cli.runtime import _build_cli_input_payload

        payload = _build_cli_input_payload(
            cli_config=CliConfig.pi(),
            messages=[Message(role="user", content="hello")],
            system_prompt="be helpful",
        )

        data = json.loads(payload)
        assert data["type"] == "prompt"
        assert "System instructions:\nbe helpful" in data["message"]
        assert payload.endswith("\n")


class TestCliRuntimeEnvironment:
    def test_build_subprocess_env_redacts_host_secrets_by_default(self) -> None:
        from swarmline.runtime.cli.runtime import _build_subprocess_env

        cli_config = CliConfig(command=["claude"], env={"EXPLICIT_TOKEN": "ok"})
        with patch.dict(
            "os.environ",
            {"PATH": "/usr/bin", "SECRET_TOKEN": "top-secret", "HOME": "/tmp/home"},
            clear=True,
        ):
            env = _build_subprocess_env(cli_config)

        assert env["PATH"] == "/usr/bin"
        assert env["HOME"] == "/tmp/home"
        assert env["EXPLICIT_TOKEN"] == "ok"
        assert "SECRET_TOKEN" not in env

    def test_build_subprocess_env_can_inherit_full_host_env_when_enabled(self) -> None:
        from swarmline.runtime.cli.runtime import _build_subprocess_env

        cli_config = CliConfig(command=["claude"], inherit_host_env=True)
        with patch.dict("os.environ", {"PATH": "/usr/bin", "SECRET_TOKEN": "top-secret"}, clear=True):
            env = _build_subprocess_env(cli_config)

        assert env["SECRET_TOKEN"] == "top-secret"


class TestCliRuntimeRun:
    """CliAgentRuntime.run() subprocess interaction."""

    async def test_cli_runtime_run_yields_parsed_events(self) -> None:
        """run() yields events parsed from subprocess stdout."""
        from swarmline.runtime.cli.runtime import CliAgentRuntime

        config = RuntimeConfig(runtime_name="cli")
        cli_config = CliConfig(command=["claude", "--print", "-"])
        rt = CliAgentRuntime(config=config, cli_config=cli_config)

        # Mock subprocess
        ndjson_line = json.dumps({
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "hello"}]},
        })
        result_line = json.dumps({"type": "result", "result": "done"})
        stdout_data = f"{ndjson_line}\n{result_line}\n".encode()

        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.stdin = MagicMock()
        mock_process.stdin.write = MagicMock()
        mock_process.stdin.drain = AsyncMock()
        mock_process.stdin.close = MagicMock()
        mock_process.stdout = _make_async_lines(stdout_data)
        mock_process.stderr = AsyncMock()
        mock_process.stderr.read = AsyncMock(return_value=b"")
        mock_process.wait = AsyncMock(return_value=0)

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            events = []
            async for event in rt.run(
                messages=[Message(role="user", content="hi")],
                system_prompt="be helpful",
                active_tools=[],
            ):
                events.append(event)

        mock_process.stdin.write.assert_called_once_with(
            b"System instructions:\nbe helpful\n\nConversation:\nuser: hi"
        )
        assert len(events) >= 2
        assert events[0].type == "assistant_delta"
        assert events[0].data["text"] == "hello"
        assert events[1].type == "final"

    async def test_cli_runtime_run_normalizes_legacy_claude_command_before_exec(self) -> None:
        """Legacy Claude command shape is upgraded before subprocess spawn."""
        from swarmline.runtime.cli.runtime import CliAgentRuntime

        config = RuntimeConfig(runtime_name="cli")
        cli_config = CliConfig(command=["claude", "--print", "--output", "stream-json", "-"])
        rt = CliAgentRuntime(config=config, cli_config=cli_config)

        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.stdin = MagicMock()
        mock_process.stdin.write = MagicMock()
        mock_process.stdin.drain = AsyncMock()
        mock_process.stdin.close = MagicMock()
        mock_process.stdout = _make_async_lines(b'{"type":"result","result":"done"}\n')
        mock_process.stderr = AsyncMock()
        mock_process.stderr.read = AsyncMock(return_value=b"")
        mock_process.wait = AsyncMock(return_value=0)

        with patch("asyncio.create_subprocess_exec", return_value=mock_process) as create_proc:
            events = []
            async for event in rt.run(
                messages=[Message(role="user", content="hi")],
                system_prompt="",
                active_tools=[],
            ):
                events.append(event)

        assert [event.type for event in events] == ["final"]
        assert create_proc.call_args.args == (
            "claude",
            "--print",
            "--output-format",
            "stream-json",
            "--verbose",
            "-",
        )

    async def test_cli_runtime_run_process_error_yields_error_event(self) -> None:
        """Non-zero exit code -> error event."""
        from swarmline.runtime.cli.runtime import CliAgentRuntime

        config = RuntimeConfig(runtime_name="cli")
        cli_config = CliConfig(command=["false"])
        rt = CliAgentRuntime(config=config, cli_config=cli_config)

        mock_process = MagicMock()
        mock_process.returncode = 1
        mock_process.stdin = MagicMock()
        mock_process.stdin.write = MagicMock()
        mock_process.stdin.drain = AsyncMock()
        mock_process.stdin.close = MagicMock()
        mock_process.stdout = _make_async_lines(b"")
        mock_process.stderr = AsyncMock()
        mock_process.stderr.read = AsyncMock(return_value=b"some error")
        mock_process.wait = AsyncMock(return_value=1)

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            events = []
            async for event in rt.run(
                messages=[Message(role="user", content="hi")],
                system_prompt="",
                active_tools=[],
            ):
                events.append(event)

        error_events = [e for e in events if e.type == "error"]
        assert len(error_events) == 1
        assert "process_error" in str(error_events[0].data) or error_events[0].data.get("kind") == "runtime_crash"

    async def test_cli_runtime_run_max_output_exceeded_yields_error(self) -> None:
        """Output exceeding max_output_bytes -> error event."""
        from swarmline.runtime.cli.runtime import CliAgentRuntime

        config = RuntimeConfig(runtime_name="cli")
        cli_config = CliConfig(command=["echo"], max_output_bytes=10)
        rt = CliAgentRuntime(config=config, cli_config=cli_config)

        # Generate more than 10 bytes
        big_line = json.dumps({"type": "result", "result": "x" * 100}) + "\n"
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.stdin = MagicMock()
        mock_process.stdin.write = MagicMock()
        mock_process.stdin.drain = AsyncMock()
        mock_process.stdin.close = MagicMock()
        mock_process.stdout = _make_async_lines(big_line.encode())
        mock_process.stderr = AsyncMock()
        mock_process.stderr.read = AsyncMock(return_value=b"")
        mock_process.wait = AsyncMock(return_value=0)

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            events = []
            async for event in rt.run(
                messages=[Message(role="user", content="hi")],
                system_prompt="",
                active_tools=[],
            ):
                events.append(event)

        error_events = [e for e in events if e.type == "error"]
        assert len(error_events) >= 1

    async def test_cli_runtime_run_clean_exit_without_final_yields_bad_model_output(
        self,
    ) -> None:
        """Exit code 0 without final event -> bad_model_output error."""
        from swarmline.runtime.cli.runtime import CliAgentRuntime

        config = RuntimeConfig(runtime_name="cli")
        cli_config = CliConfig(command=["my-agent", "--json"])
        rt = CliAgentRuntime(config=config, cli_config=cli_config)

        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.stdin = MagicMock()
        mock_process.stdin.write = MagicMock()
        mock_process.stdin.drain = AsyncMock()
        mock_process.stdin.close = MagicMock()
        mock_process.stdout = _make_async_lines(b'{"step":"processing"}\n')
        mock_process.stderr = AsyncMock()
        mock_process.stderr.read = AsyncMock(return_value=b"")
        mock_process.wait = AsyncMock(return_value=0)

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            events = []
            async for event in rt.run(
                messages=[Message(role="user", content="hi")],
                system_prompt="",
                active_tools=[],
            ):
                events.append(event)

        assert events[-1].type == "error"
        assert events[-1].data["kind"] == "bad_model_output"
        assert "without a final" in events[-1].data["message"]


class TestCliRuntimeCancel:
    """CliAgentRuntime.cancel() terminates subprocess."""

    async def test_cli_runtime_cancel_no_process_no_error(self) -> None:
        """cancel() with no active process does not raise."""
        from swarmline.runtime.cli.runtime import CliAgentRuntime

        config = RuntimeConfig(runtime_name="cli")
        rt = CliAgentRuntime(config=config)
        rt.cancel()  # Should not raise

    async def test_cli_runtime_cancel_running_process_yields_cancelled_error(self) -> None:
        from swarmline.runtime.cli.runtime import CliAgentRuntime

        config = RuntimeConfig(runtime_name="cli")
        rt = CliAgentRuntime(config=config)

        terminated = asyncio.Event()
        mock_process = MagicMock()
        mock_process.returncode = None
        mock_process.stdin = MagicMock()
        mock_process.stdin.write = MagicMock()
        mock_process.stdin.drain = AsyncMock()
        mock_process.stdin.close = MagicMock()

        async def _stdout_iter():
            await terminated.wait()
            return
            yield  # pragma: no cover

        async def _wait():
            await terminated.wait()
            mock_process.returncode = -15
            return -15

        def _terminate() -> None:
            terminated.set()

        mock_process.stdout = _stdout_iter()
        mock_process.stderr = AsyncMock()
        mock_process.stderr.read = AsyncMock(return_value=b"")
        mock_process.wait = AsyncMock(side_effect=_wait)
        mock_process.terminate = MagicMock(side_effect=_terminate)
        mock_process.kill = MagicMock()

        async def _collect() -> list[Any]:
            events = []
            async for event in rt.run(
                messages=[Message(role="user", content="hi")],
                system_prompt="",
                active_tools=[],
            ):
                events.append(event)
            return events

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            task = asyncio.create_task(_collect())
            await asyncio.sleep(0)
            rt.cancel()
            events = await task

        assert events[-1].type == "error"
        assert events[-1].data["kind"] == "cancelled"
        assert "cancelled" in events[-1].data["message"].lower()
        mock_process.terminate.assert_called_once()


class TestCliRuntimeContextManager:
    """CliAgentRuntime async context manager."""

    async def test_cli_runtime_aenter_returns_self(self) -> None:
        from swarmline.runtime.cli.runtime import CliAgentRuntime

        config = RuntimeConfig(runtime_name="cli")
        rt = CliAgentRuntime(config=config)
        async with rt as ctx:
            assert ctx is rt


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _async_line_iter(data: bytes):
    """Simulate async iteration over stdout lines."""
    for line in data.split(b"\n"):
        if line:
            yield line + b"\n"


def _make_async_lines(data: bytes):
    """Create an async iterable mimicking process.stdout."""
    return _async_line_iter(data)
