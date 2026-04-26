"""Tests for PI SDK runtime integration."""

from __future__ import annotations

import dataclasses
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarmline.runtime.types import Message, RuntimeConfig, ToolSpec


class TestPiSdkOptions:
    def test_defaults_are_safe(self) -> None:
        from swarmline.runtime.pi_sdk.types import PiSdkOptions

        options = PiSdkOptions()

        assert options.toolset == "none"
        assert options.bridge_command == ()
        assert options.package_name == "@mariozechner/pi-coding-agent"

    def test_invalid_toolset_raises(self) -> None:
        from swarmline.runtime.pi_sdk.types import PiSdkOptions

        with pytest.raises(ValueError, match="toolset"):
            PiSdkOptions(toolset="danger")  # type: ignore[arg-type]

    def test_frozen(self) -> None:
        from swarmline.runtime.pi_sdk.types import PiSdkOptions

        options = PiSdkOptions()
        with pytest.raises(dataclasses.FrozenInstanceError):
            options.toolset = "readonly"  # type: ignore[misc]


class TestPiEventMapper:
    def test_maps_text_delta(self) -> None:
        from swarmline.runtime.pi_sdk.event_mapper import map_pi_bridge_event

        event = map_pi_bridge_event({"type": "assistant_delta", "text": "hello"})

        assert event is not None
        assert event.type == "assistant_delta"
        assert event.data["text"] == "hello"

    def test_maps_tool_start_and_finish(self) -> None:
        from swarmline.runtime.pi_sdk.event_mapper import map_pi_bridge_event

        started = map_pi_bridge_event(
            {
                "type": "tool_call_started",
                "name": "calc",
                "correlation_id": "t1",
                "args": {"x": 1},
            }
        )
        finished = map_pi_bridge_event(
            {
                "type": "tool_call_finished",
                "name": "calc",
                "correlation_id": "t1",
                "ok": True,
                "result_summary": "2",
            }
        )

        assert started is not None
        assert started.type == "tool_call_started"
        assert started.data["correlation_id"] == "t1"
        assert finished is not None
        assert finished.type == "tool_call_finished"
        assert finished.data["ok"] is True

    def test_maps_final_with_metadata(self) -> None:
        from swarmline.runtime.pi_sdk.event_mapper import map_pi_bridge_event

        event = map_pi_bridge_event(
            {
                "type": "final",
                "text": "done",
                "session_id": "pi-session",
                "usage": {"input": 1},
                "total_cost_usd": 0.01,
            }
        )

        assert event is not None
        assert event.type == "final"
        assert event.data["text"] == "done"
        assert event.data["session_id"] == "pi-session"
        assert event.data["usage"] == {"input": 1}

    def test_maps_error(self) -> None:
        from swarmline.runtime.pi_sdk.event_mapper import map_pi_bridge_event

        event = map_pi_bridge_event(
            {"type": "error", "message": "boom", "kind": "runtime_crash"}
        )

        assert event is not None
        assert event.type == "error"
        assert event.data["kind"] == "runtime_crash"
        assert "boom" in event.data["message"]


class TestPiSdkRuntime:
    def test_runtime_is_agent_runtime(self) -> None:
        from swarmline.runtime.base import AgentRuntime
        from swarmline.runtime.pi_sdk.runtime import PiSdkRuntime

        runtime = PiSdkRuntime(config=RuntimeConfig(runtime_name="pi_sdk"))

        assert isinstance(runtime, AgentRuntime)

    def test_build_bridge_command_defaults_to_packaged_bridge(self) -> None:
        from swarmline.runtime.pi_sdk.runtime import PiSdkRuntime
        from swarmline.runtime.pi_sdk.types import PiSdkOptions

        runtime = PiSdkRuntime(
            config=RuntimeConfig(runtime_name="pi_sdk"),
            pi_options=PiSdkOptions(),
        )

        command = runtime._build_bridge_command()

        assert command[0] == "node"
        assert command[1].endswith("bridge.mjs")

    def test_build_run_request_serializes_safe_tool_options(self) -> None:
        from swarmline.runtime.pi_sdk.runtime import PiSdkRuntime
        from swarmline.runtime.pi_sdk.types import PiSdkOptions

        runtime = PiSdkRuntime(
            config=RuntimeConfig(
                runtime_name="pi_sdk", model="anthropic:claude-sonnet-4-20250514"
            ),
            pi_options=PiSdkOptions(toolset="readonly", cwd="/repo"),
            tool_executors={"calc": lambda x: str(x)},
        )
        request = runtime._build_run_request(
            messages=[Message(role="user", content="hi")],
            system_prompt="be useful",
            active_tools=[
                ToolSpec(
                    name="calc",
                    description="Calculator",
                    parameters={"type": "object"},
                    is_local=True,
                )
            ],
        )

        assert request["type"] == "run"
        assert request["options"]["toolset"] == "readonly"
        assert request["options"]["cwd"] == "/repo"
        assert request["runtime"]["model"] == "anthropic:claude-sonnet-4-20250514"
        assert request["tools"][0]["name"] == "calc"

    async def test_run_yields_events_from_fake_bridge(self) -> None:
        from swarmline.runtime.pi_sdk.runtime import PiSdkRuntime
        from swarmline.runtime.pi_sdk.types import PiSdkOptions

        runtime = PiSdkRuntime(
            config=RuntimeConfig(runtime_name="pi_sdk"),
            pi_options=PiSdkOptions(bridge_command=("fake-pi-bridge",)),
        )

        lines = (
            b"\n".join(
                [
                    json.dumps({"type": "assistant_delta", "text": "hello"}).encode(),
                    json.dumps({"type": "final", "text": "hello"}).encode(),
                ]
            )
            + b"\n"
        )
        process = _make_process(stdout_data=lines, returncode=0)

        with patch("asyncio.create_subprocess_exec", return_value=process):
            events = [
                event
                async for event in runtime.run(
                    messages=[Message(role="user", content="hi")],
                    system_prompt="sys",
                    active_tools=[],
                )
            ]

        assert [event.type for event in events] == ["assistant_delta", "final"]
        assert (
            json.loads(process.stdin.write.call_args.args[0].decode())["type"] == "run"
        )

    async def test_run_executes_swarmline_tool_request(self) -> None:
        from swarmline.runtime.pi_sdk.runtime import PiSdkRuntime
        from swarmline.runtime.pi_sdk.types import PiSdkOptions

        async def calc(x: int) -> str:
            return str(x + 1)

        runtime = PiSdkRuntime(
            config=RuntimeConfig(runtime_name="pi_sdk"),
            pi_options=PiSdkOptions(bridge_command=("fake-pi-bridge",)),
            tool_executors={"calc": calc},
        )
        lines = (
            b"\n".join(
                [
                    json.dumps(
                        {
                            "type": "tool_request",
                            "id": "req-1",
                            "name": "calc",
                            "args": {"x": 41},
                        }
                    ).encode(),
                    json.dumps({"type": "final", "text": "done"}).encode(),
                ]
            )
            + b"\n"
        )
        process = _make_process(stdout_data=lines, returncode=0)

        with patch("asyncio.create_subprocess_exec", return_value=process):
            events = [
                event
                async for event in runtime.run(
                    messages=[Message(role="user", content="hi")],
                    system_prompt="sys",
                    active_tools=[
                        ToolSpec(
                            name="calc",
                            description="Calculator",
                            parameters={"type": "object"},
                            is_local=True,
                        )
                    ],
                )
            ]

        writes = [
            json.loads(call.args[0].decode())
            for call in process.stdin.write.call_args_list
        ]
        assert writes[-1]["type"] == "tool_response"
        assert writes[-1]["ok"] is True
        assert writes[-1]["result"] == "42"
        assert [event.type for event in events] == [
            "tool_call_started",
            "tool_call_finished",
            "final",
        ]


async def _async_line_iter(data: bytes):
    for line in data.split(b"\n"):
        if line:
            yield line + b"\n"


def _make_process(stdout_data: bytes, returncode: int) -> Any:
    process = MagicMock()
    process.returncode = returncode
    process.stdin = MagicMock()
    process.stdin.write = MagicMock()
    process.stdin.drain = AsyncMock()
    process.stdin.close = MagicMock()
    process.stdout = _async_line_iter(stdout_data)
    process.stderr = AsyncMock()
    process.stderr.read = AsyncMock(return_value=b"")
    process.wait = AsyncMock(return_value=returncode)
    process.terminate = MagicMock()
    process.kill = MagicMock()
    return process


# ---------------------------------------------------------------------------
# Stage 2 of plans/2026-04-27_fix_security-audit.md — pi_sdk env allowlist
# Closes audit finding P1 #2: Node bridge previously inherited full host env
# (OPENAI_API_KEY, AWS_*, CI tokens) — now uses an allowlist by default.
# ---------------------------------------------------------------------------


class TestPiSdkOptionsEnvAllowlist:
    """PiSdkOptions exposes secure-by-default env handling fields."""

    def test_pi_sdk_options_has_inherit_host_env_default_false(self) -> None:
        from swarmline.runtime.pi_sdk.types import PiSdkOptions

        options = PiSdkOptions()
        assert options.inherit_host_env is False

    def test_pi_sdk_options_default_allowlist_contains_provider_keys(self) -> None:
        from swarmline.runtime.pi_sdk.types import (
            DEFAULT_PI_SDK_ENV_ALLOWLIST,
            PiSdkOptions,
        )

        options = PiSdkOptions()
        assert options.env_allowlist is DEFAULT_PI_SDK_ENV_ALLOWLIST
        # Node + provider keys explicitly required for pi-coding-agent
        assert "NODE_PATH" in DEFAULT_PI_SDK_ENV_ALLOWLIST
        assert "OPENAI_API_KEY" in DEFAULT_PI_SDK_ENV_ALLOWLIST
        assert "ANTHROPIC_API_KEY" in DEFAULT_PI_SDK_ENV_ALLOWLIST
        # Generic CLI defaults still inherited
        assert "PATH" in DEFAULT_PI_SDK_ENV_ALLOWLIST
        assert "HOME" in DEFAULT_PI_SDK_ENV_ALLOWLIST
        # Arbitrary secrets must NOT be in the default allowlist
        assert "AWS_SECRET_ACCESS_KEY" not in DEFAULT_PI_SDK_ENV_ALLOWLIST

    def test_pi_sdk_options_env_dict_default_empty(self) -> None:
        from swarmline.runtime.pi_sdk.types import PiSdkOptions

        options = PiSdkOptions()
        assert options.env == {}


class TestPiSdkSubprocessEnvIsolation:
    """Verifies pi_sdk runtime passes env= to create_subprocess_exec."""

    async def _drain_runtime(self, runtime: Any) -> None:
        """Run a minimal final-only fake bridge so the test exits cleanly."""
        async for _ in runtime.run(
            messages=[Message(role="user", content="hi")],
            system_prompt="sys",
            active_tools=[],
        ):
            pass

    async def test_pi_sdk_excludes_arbitrary_secret_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Default allowlist must NOT pass MY_LEAKY_SECRET to the subprocess."""
        from swarmline.runtime.pi_sdk.runtime import PiSdkRuntime
        from swarmline.runtime.pi_sdk.types import PiSdkOptions

        monkeypatch.setenv("MY_LEAKY_SECRET", "value-must-not-leak")

        runtime = PiSdkRuntime(
            config=RuntimeConfig(runtime_name="pi_sdk"),
            pi_options=PiSdkOptions(bridge_command=("fake-pi-bridge",)),
        )
        process = _make_process(
            stdout_data=json.dumps({"type": "final", "text": ""}).encode() + b"\n",
            returncode=0,
        )
        with patch(
            "asyncio.create_subprocess_exec",
            return_value=process,
        ) as exec_mock:
            await self._drain_runtime(runtime)

        assert exec_mock.called
        kwargs = exec_mock.call_args.kwargs
        assert "env" in kwargs, "pi_sdk must pass env= to create_subprocess_exec"
        env: dict[str, str] = kwargs["env"]
        assert "MY_LEAKY_SECRET" not in env

    async def test_pi_sdk_includes_openai_api_key_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OPENAI_API_KEY is needed by pi-coding-agent and is in default allowlist."""
        from swarmline.runtime.pi_sdk.runtime import PiSdkRuntime
        from swarmline.runtime.pi_sdk.types import PiSdkOptions

        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-from-host")
        runtime = PiSdkRuntime(
            config=RuntimeConfig(runtime_name="pi_sdk"),
            pi_options=PiSdkOptions(bridge_command=("fake-pi-bridge",)),
        )
        process = _make_process(
            stdout_data=json.dumps({"type": "final", "text": ""}).encode() + b"\n",
            returncode=0,
        )
        with patch(
            "asyncio.create_subprocess_exec",
            return_value=process,
        ) as exec_mock:
            await self._drain_runtime(runtime)

        env = exec_mock.call_args.kwargs["env"]
        assert env.get("OPENAI_API_KEY") == "sk-test-from-host"

    async def test_pi_sdk_inherits_full_env_when_inherit_host_env_true(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Explicit opt-in restores legacy behavior for downstream compatibility."""
        from swarmline.runtime.pi_sdk.runtime import PiSdkRuntime
        from swarmline.runtime.pi_sdk.types import PiSdkOptions

        monkeypatch.setenv("MY_LEAKY_SECRET", "value-must-leak-now")
        runtime = PiSdkRuntime(
            config=RuntimeConfig(runtime_name="pi_sdk"),
            pi_options=PiSdkOptions(
                bridge_command=("fake-pi-bridge",),
                inherit_host_env=True,
            ),
        )
        process = _make_process(
            stdout_data=json.dumps({"type": "final", "text": ""}).encode() + b"\n",
            returncode=0,
        )
        with patch(
            "asyncio.create_subprocess_exec",
            return_value=process,
        ) as exec_mock:
            await self._drain_runtime(runtime)

        env = exec_mock.call_args.kwargs["env"]
        assert env.get("MY_LEAKY_SECRET") == "value-must-leak-now"

    async def test_pi_sdk_explicit_overrides_take_precedence(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PiSdkOptions.env wins over host os.environ for the same key."""
        from swarmline.runtime.pi_sdk.runtime import PiSdkRuntime
        from swarmline.runtime.pi_sdk.types import PiSdkOptions

        monkeypatch.setenv("OPENAI_API_KEY", "sk-from-host")
        runtime = PiSdkRuntime(
            config=RuntimeConfig(runtime_name="pi_sdk"),
            pi_options=PiSdkOptions(
                bridge_command=("fake-pi-bridge",),
                env={"OPENAI_API_KEY": "sk-explicit-override"},
            ),
        )
        process = _make_process(
            stdout_data=json.dumps({"type": "final", "text": ""}).encode() + b"\n",
            returncode=0,
        )
        with patch(
            "asyncio.create_subprocess_exec",
            return_value=process,
        ) as exec_mock:
            await self._drain_runtime(runtime)

        env = exec_mock.call_args.kwargs["env"]
        assert env.get("OPENAI_API_KEY") == "sk-explicit-override"

    async def test_pi_sdk_custom_allowlist_passes_extra_var(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Custom env_allowlist allows operator-controlled extras through."""
        from swarmline.runtime.pi_sdk.runtime import PiSdkRuntime
        from swarmline.runtime.pi_sdk.types import (
            DEFAULT_PI_SDK_ENV_ALLOWLIST,
            PiSdkOptions,
        )

        monkeypatch.setenv("MY_BUSINESS_VAR", "operator-approved")
        runtime = PiSdkRuntime(
            config=RuntimeConfig(runtime_name="pi_sdk"),
            pi_options=PiSdkOptions(
                bridge_command=("fake-pi-bridge",),
                env_allowlist=DEFAULT_PI_SDK_ENV_ALLOWLIST | {"MY_BUSINESS_VAR"},
            ),
        )
        process = _make_process(
            stdout_data=json.dumps({"type": "final", "text": ""}).encode() + b"\n",
            returncode=0,
        )
        with patch(
            "asyncio.create_subprocess_exec",
            return_value=process,
        ) as exec_mock:
            await self._drain_runtime(runtime)

        env = exec_mock.call_args.kwargs["env"]
        assert env.get("MY_BUSINESS_VAR") == "operator-approved"
