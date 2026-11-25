"""Cross-runtime conformance matrix (RUNTIME-PARITY-PLAN Workstream F1).

Each scenario is parametrized over all six public runtimes with the runtime
boundary mocked using the same seams the per-runtime unit tests use:

- thin:          injectable ``llm_call`` (JSON envelope contract)
- claude_sdk:    ``ClaudeCodeRuntime(adapter=FakeAdapter)``
- deepagents:    patched ``_stream_langchain`` / ``_build_llm`` fake
                 ``astream_events``
- cli:           fake subprocess with NDJSON stdout
                 (``asyncio.create_subprocess_exec`` patched)
- openai_agents: fake ``agents`` module injected into ``sys.modules``
- pi_sdk:        fake Node bridge process replaying JSONL events

The contract under test is the RuntimeEvent stream, driven through each
runtime class directly (not the Agent facade). Scenarios are gated on the
declared capability matrix: a runtime whose level for the scenario's
dimension is ``"none"`` is skipped with an explicit reason, so the scenario
x runtime coverage stays visible in the test report.
"""

from __future__ import annotations

import asyncio
import json
import sys
import types
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarmline.runtime.capabilities import get_runtime_capabilities
from swarmline.runtime.cancellation import CancellationToken
from swarmline.runtime.types import (
    Message,
    RuntimeConfig,
    RuntimeEvent,
    ThinkingConfig,
    ToolSpec,
)

RUNTIMES: tuple[str, ...] = (
    "thin",
    "claude_sdk",
    "deepagents",
    "cli",
    "openai_agents",
    "pi_sdk",
)

_USER_MESSAGES = [Message(role="user", content="hello")]


def _skip_if_capability_none(runtime: str, dimension: str) -> None:
    level = get_runtime_capabilities(runtime).level(dimension)
    if level == "none":
        pytest.skip(f"{runtime}: capability '{dimension}' declared 'none'")


def _finals(events: list[RuntimeEvent]) -> list[RuntimeEvent]:
    return [e for e in events if e.type == "final"]


def _delta_text(events: list[RuntimeEvent]) -> str:
    return "".join(
        str(e.data.get("text", "")) for e in events if e.type == "assistant_delta"
    )


# ---------------------------------------------------------------------------
# thin driver — injectable llm_call (tests/unit/test_thin_* seam)
# ---------------------------------------------------------------------------


def _thin_final_json(text: str) -> str:
    return json.dumps({"type": "final", "final_message": text})


async def _collect_thin(
    runtime: Any,
    config: RuntimeConfig,
    *,
    active_tools: list[ToolSpec] | None = None,
    mode_hint: str = "conversational",
) -> list[RuntimeEvent]:
    events: list[RuntimeEvent] = []
    async for event in runtime.run(
        messages=list(_USER_MESSAGES),
        system_prompt="sys",
        active_tools=active_tools or [],
        config=config,
        mode_hint=mode_hint,
    ):
        events.append(event)
    return events


class _ThinDriver:
    @staticmethod
    async def stream_text() -> list[RuntimeEvent]:
        from swarmline.runtime.thin import ThinRuntime

        final_json = _thin_final_json("Hello streamed world")

        async def llm(messages: Any, system_prompt: str, **kwargs: Any) -> Any:
            if kwargs.get("stream"):

                async def _gen() -> AsyncIterator[str]:
                    for i in range(0, len(final_json), 7):
                        yield final_json[i : i + 7]

                return _gen()
            return final_json

        config = RuntimeConfig(runtime_name="thin")
        runtime = ThinRuntime(config=config, llm_call=llm)
        return await _collect_thin(runtime, config)

    @staticmethod
    async def new_messages() -> list[RuntimeEvent]:
        from swarmline.runtime.thin import ThinRuntime

        async def llm(messages: Any, system_prompt: str, **kwargs: Any) -> str:
            return _thin_final_json("done")

        config = RuntimeConfig(runtime_name="thin")
        runtime = ThinRuntime(config=config, llm_call=llm)
        return await _collect_thin(runtime, config)

    @staticmethod
    async def thinking() -> list[RuntimeEvent]:
        from swarmline.runtime.thin import ThinRuntime
        from swarmline.runtime.thin.llm_client import LlmCallResult

        async def llm(messages: Any, system_prompt: str, **kwargs: Any) -> Any:
            return LlmCallResult(text=_thin_final_json("done"), thinking="thought hard")

        # thinking configured -> buffered postprocessing path emits
        # thinking_delta from LlmCallResult.thinking.
        config = RuntimeConfig(
            runtime_name="thin", thinking=ThinkingConfig(budget_tokens=1024)
        )
        runtime = ThinRuntime(config=config, llm_call=llm)
        return await _collect_thin(runtime, config)

    @staticmethod
    async def usage() -> list[RuntimeEvent]:
        from swarmline.runtime.thin import ThinRuntime
        from swarmline.runtime.thin.usage import (
            record_native_usage,
            reset_native_usage,
        )

        async def llm(messages: Any, system_prompt: str, **kwargs: Any) -> str:
            record_native_usage(100, 7)
            return _thin_final_json("done")

        reset_native_usage()
        try:
            config = RuntimeConfig(runtime_name="thin")
            runtime = ThinRuntime(config=config, llm_call=llm)
            return await _collect_thin(runtime, config)
        finally:
            reset_native_usage()

    @staticmethod
    async def cancellation() -> list[RuntimeEvent]:
        from swarmline.runtime.thin import ThinRuntime

        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_llm(messages: Any, system_prompt: str, **kwargs: Any) -> str:
            started.set()
            await release.wait()
            return _thin_final_json("slow")

        token = CancellationToken()
        config = RuntimeConfig(runtime_name="thin", cancellation_token=token)
        runtime = ThinRuntime(config=config, llm_call=slow_llm)

        events: list[RuntimeEvent] = []

        async def consume() -> None:
            async for event in runtime.run(
                messages=list(_USER_MESSAGES),
                system_prompt="sys",
                active_tools=[],
                config=config,
            ):
                events.append(event)

        task = asyncio.create_task(consume())
        await started.wait()
        runtime.cancel()
        release.set()
        await task
        return events

    @staticmethod
    async def tool_calls() -> list[RuntimeEvent]:
        from swarmline.runtime.thin import ThinRuntime

        responses = iter(
            [
                json.dumps(
                    {
                        "type": "tool_call",
                        "tool": {
                            "name": "calc",
                            "args": {"x": 1},
                            "correlation_id": "c1",
                        },
                    }
                ),
                _thin_final_json("done"),
            ]
        )

        async def llm(messages: Any, system_prompt: str, **kwargs: Any) -> str:
            return next(responses, _thin_final_json("fallback"))

        config = RuntimeConfig(runtime_name="thin")
        runtime = ThinRuntime(
            config=config, llm_call=llm, local_tools={"calc": lambda args: {"r": 2}}
        )
        tools = [ToolSpec(name="calc", description="calc", parameters={})]
        return await _collect_thin(
            runtime, config, active_tools=tools, mode_hint="react"
        )


# ---------------------------------------------------------------------------
# claude_sdk driver — fake adapter (tests/unit/test_claude_code_runtime.py seam)
# ---------------------------------------------------------------------------


@dataclass
class _FakeSdkStreamEvent:
    type: str
    text: str = ""
    tool_name: str = ""
    tool_input: dict[str, Any] | None = None
    tool_result: str = ""
    correlation_id: str = ""
    tool_error: bool = False
    is_final: bool = False
    session_id: str | None = None
    total_cost_usd: float | None = None
    usage: dict[str, Any] | None = None
    structured_output: Any = None


class _FakeSdkAdapter:
    def __init__(self, events: list[_FakeSdkStreamEvent]) -> None:
        self._events = events

    @property
    def is_connected(self) -> bool:
        return True

    async def stream_reply(self, user_text: str) -> AsyncIterator[_FakeSdkStreamEvent]:
        for event in self._events:
            yield event

    async def disconnect(self) -> None:
        return None


async def _collect_claude(events: list[_FakeSdkStreamEvent]) -> list[RuntimeEvent]:
    from swarmline.runtime.claude_code import ClaudeCodeRuntime

    runtime = ClaudeCodeRuntime(adapter=_FakeSdkAdapter(events))
    collected: list[RuntimeEvent] = []
    async for event in runtime.run(
        messages=list(_USER_MESSAGES), system_prompt="sys", active_tools=[]
    ):
        collected.append(event)
    return collected


class _ClaudeSdkDriver:
    @staticmethod
    async def stream_text() -> list[RuntimeEvent]:
        return await _collect_claude(
            [
                _FakeSdkStreamEvent(type="text_delta", text="Hello "),
                _FakeSdkStreamEvent(type="text_delta", text="world"),
                _FakeSdkStreamEvent(type="done", text="Hello world", is_final=True),
            ]
        )

    new_messages = stream_text

    @staticmethod
    async def thinking() -> list[RuntimeEvent]:
        return await _collect_claude(
            [
                _FakeSdkStreamEvent(type="thinking_delta", text="pondering"),
                _FakeSdkStreamEvent(type="text_delta", text="answer"),
                _FakeSdkStreamEvent(type="done", text="answer", is_final=True),
            ]
        )

    @staticmethod
    async def usage() -> list[RuntimeEvent]:
        return await _collect_claude(
            [
                _FakeSdkStreamEvent(type="text_delta", text="answer"),
                _FakeSdkStreamEvent(
                    type="done",
                    text="answer",
                    is_final=True,
                    usage={"input_tokens": 10, "output_tokens": 5},
                    total_cost_usd=0.2,
                ),
            ]
        )

    @staticmethod
    async def cancellation() -> list[RuntimeEvent]:
        from swarmline.runtime.claude_code import ClaudeCodeRuntime

        events = [
            _FakeSdkStreamEvent(type="text_delta", text="Hello "),
            _FakeSdkStreamEvent(type="text_delta", text="world"),
            _FakeSdkStreamEvent(type="done", text="Hello world", is_final=True),
        ]
        runtime = ClaudeCodeRuntime(adapter=_FakeSdkAdapter(events))
        collected: list[RuntimeEvent] = []
        async for event in runtime.run(
            messages=list(_USER_MESSAGES), system_prompt="sys", active_tools=[]
        ):
            collected.append(event)
            runtime.cancel()
        return collected

    @staticmethod
    async def tool_calls() -> list[RuntimeEvent]:
        return await _collect_claude(
            [
                _FakeSdkStreamEvent(
                    type="tool_use_start",
                    tool_name="calc",
                    tool_input={"x": 1},
                    correlation_id="t1",
                ),
                _FakeSdkStreamEvent(
                    type="tool_use_result",
                    tool_name="calc",
                    tool_result="2",
                    correlation_id="t1",
                    tool_error=False,
                ),
                _FakeSdkStreamEvent(type="text_delta", text="done"),
                _FakeSdkStreamEvent(type="done", text="done", is_final=True),
            ]
        )


# ---------------------------------------------------------------------------
# deepagents driver — patched stream seams
# (tests/unit/test_deepagents_runtime.py pattern)
# ---------------------------------------------------------------------------


def _deepagents_runtime(config: RuntimeConfig | None = None) -> Any:
    pytest.importorskip("deepagents", reason="deepagents is not installed")
    from swarmline.runtime.deepagents import DeepAgentsRuntime

    return DeepAgentsRuntime(config=config)


async def _collect_deepagents(
    runtime: Any, config: RuntimeConfig | None = None
) -> list[RuntimeEvent]:
    events: list[RuntimeEvent] = []
    async for event in runtime.run(
        messages=list(_USER_MESSAGES),
        system_prompt="sys",
        active_tools=[],
        config=config,
    ):
        events.append(event)
    return events


class _DeepAgentsDriver:
    @staticmethod
    async def stream_text() -> list[RuntimeEvent]:
        runtime = _deepagents_runtime()

        async def _fake_stream(**kwargs: Any) -> AsyncIterator[RuntimeEvent]:
            yield RuntimeEvent.assistant_delta("Hello ")
            yield RuntimeEvent.assistant_delta("world")

        with (
            patch(
                "swarmline.runtime.deepagents._check_langchain_available",
                return_value=None,
            ),
            patch.object(runtime, "_stream_langchain", side_effect=_fake_stream),
        ):
            return await _collect_deepagents(runtime)

    new_messages = stream_text

    @staticmethod
    async def thinking() -> list[RuntimeEvent]:  # pragma: no cover - gated
        raise AssertionError("deepagents thinking_stream is 'none'; gated by skip")

    @staticmethod
    async def usage() -> list[RuntimeEvent]:
        from types import SimpleNamespace

        runtime = _deepagents_runtime()

        chunk = SimpleNamespace(content="hi")
        end = SimpleNamespace(
            content="",
            usage_metadata={
                "input_tokens": 10,
                "output_tokens": 5,
                "total_tokens": 15,
            },
        )

        async def fake_astream_events(*args: Any, **kwargs: Any) -> AsyncIterator[Any]:
            yield {"event": "on_chat_model_stream", "data": {"chunk": chunk}}
            yield {"event": "on_chat_model_end", "data": {"output": end}}

        mock_runnable = AsyncMock()
        mock_runnable.astream_events = fake_astream_events

        with (
            patch(
                "swarmline.runtime.deepagents._check_langchain_available",
                return_value=None,
            ),
            patch.object(runtime, "_build_llm", return_value=mock_runnable),
        ):
            return await _collect_deepagents(runtime)

    @staticmethod
    async def cancellation() -> list[RuntimeEvent]:
        from types import SimpleNamespace

        token = CancellationToken()
        config = RuntimeConfig(runtime_name="deepagents", cancellation_token=token)
        runtime = _deepagents_runtime(config)

        chunk1 = SimpleNamespace(content="part1")
        chunk2 = SimpleNamespace(content="part2")

        async def fake_astream_events(*args: Any, **kwargs: Any) -> AsyncIterator[Any]:
            yield {"event": "on_chat_model_stream", "data": {"chunk": chunk1}}
            token.cancel()
            yield {"event": "on_chat_model_stream", "data": {"chunk": chunk2}}

        mock_runnable = AsyncMock()
        mock_runnable.astream_events = fake_astream_events

        with (
            patch(
                "swarmline.runtime.deepagents._check_langchain_available",
                return_value=None,
            ),
            patch.object(runtime, "_build_llm", return_value=mock_runnable),
        ):
            return await _collect_deepagents(runtime, config)

    @staticmethod
    async def tool_calls() -> list[RuntimeEvent]:
        runtime = _deepagents_runtime()

        async def fake_astream_events(*args: Any, **kwargs: Any) -> AsyncIterator[Any]:
            yield {
                "event": "on_tool_start",
                "name": "calc",
                "data": {"input": {"x": 1}},
                "run_id": "run-1",
            }
            yield {
                "event": "on_tool_end",
                "name": "calc",
                "data": {"output": "2"},
                "run_id": "run-1",
            }

        mock_runnable = AsyncMock()
        mock_runnable.astream_events = fake_astream_events

        with (
            patch(
                "swarmline.runtime.deepagents._check_langchain_available",
                return_value=None,
            ),
            patch.object(runtime, "_build_llm", return_value=mock_runnable),
        ):
            return await _collect_deepagents(runtime)


# ---------------------------------------------------------------------------
# cli driver — fake subprocess with NDJSON stdout
# (tests/unit/test_cli_runtime.py / test_agent_conversation.py seam)
# ---------------------------------------------------------------------------


async def _async_line_iter(data: bytes) -> AsyncIterator[bytes]:
    for line in data.split(b"\n"):
        if line:
            yield line + b"\n"


def _make_cli_process(stdout_data: bytes, returncode: int = 0) -> MagicMock:
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


def _cli_runtime(cli_config: Any | None = None) -> Any:
    from swarmline.runtime.cli.runtime import CliAgentRuntime
    from swarmline.runtime.cli.types import CliConfig

    return CliAgentRuntime(
        config=RuntimeConfig(runtime_name="cli"),
        cli_config=cli_config or CliConfig(command=["claude", "--print", "-"]),
    )


async def _collect_cli(runtime: Any, process: MagicMock) -> list[RuntimeEvent]:
    events: list[RuntimeEvent] = []
    with patch("asyncio.create_subprocess_exec", return_value=process):
        async for event in runtime.run(
            messages=list(_USER_MESSAGES), system_prompt="sys", active_tools=[]
        ):
            events.append(event)
    return events


class _CliDriver:
    @staticmethod
    async def stream_text() -> list[RuntimeEvent]:
        lines = [
            json.dumps(
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "text", "text": "Hello "}]},
                }
            ),
            json.dumps(
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "text", "text": "world"}]},
                }
            ),
            json.dumps({"type": "result", "result": "Hello world"}),
        ]
        process = _make_cli_process(("\n".join(lines) + "\n").encode())
        return await _collect_cli(_cli_runtime(), process)

    @staticmethod
    async def new_messages() -> list[RuntimeEvent]:
        from swarmline.runtime.cli.types import CliConfig

        # ClaudeNdjsonParser finals carry no new_messages; the PI RPC preset
        # does (agent_end carries the message history), so drive that parser.
        lines = [
            json.dumps(
                {
                    "type": "message_update",
                    "assistantMessageEvent": {"type": "text_delta", "delta": "done"},
                }
            ),
            json.dumps(
                {
                    "type": "agent_end",
                    "messages": [{"role": "assistant", "content": "done"}],
                }
            ),
        ]
        process = _make_cli_process(("\n".join(lines) + "\n").encode())
        return await _collect_cli(_cli_runtime(CliConfig.pi()), process)

    @staticmethod
    async def thinking() -> list[RuntimeEvent]:  # pragma: no cover - gated
        raise AssertionError("cli thinking_stream is 'none'; gated by skip")

    @staticmethod
    async def usage() -> list[RuntimeEvent]:  # pragma: no cover - gated
        raise AssertionError("cli usage_reporting is 'none'; gated by skip")

    @staticmethod
    async def cancellation() -> list[RuntimeEvent]:
        runtime = _cli_runtime()

        terminated = asyncio.Event()
        process = MagicMock()
        process.returncode = None
        process.stdin = MagicMock()
        process.stdin.write = MagicMock()
        process.stdin.drain = AsyncMock()
        process.stdin.close = MagicMock()
        process.stderr = AsyncMock()
        process.stderr.read = AsyncMock(return_value=b"")
        process.kill = MagicMock()

        async def _stdout_iter() -> AsyncIterator[bytes]:
            await terminated.wait()
            return
            yield b""  # pragma: no cover

        async def _wait() -> int:
            await terminated.wait()
            process.returncode = -15
            return -15

        process.stdout = _stdout_iter()
        process.wait = AsyncMock(side_effect=_wait)
        process.terminate = MagicMock(side_effect=terminated.set)

        events: list[RuntimeEvent] = []

        async def _consume() -> None:
            async for event in runtime.run(
                messages=list(_USER_MESSAGES), system_prompt="sys", active_tools=[]
            ):
                events.append(event)

        with patch("asyncio.create_subprocess_exec", return_value=process):
            task = asyncio.create_task(_consume())
            await asyncio.sleep(0)
            runtime.cancel()
            await task
        return events

    @staticmethod
    async def tool_calls() -> list[RuntimeEvent]:  # pragma: no cover - gated
        raise AssertionError("cli has no custom-tool seam; gated by skip")


# ---------------------------------------------------------------------------
# openai_agents driver — fake `agents` module in sys.modules
# (tests/unit/test_openai_agents_runtime.py seam)
# ---------------------------------------------------------------------------


@dataclass
class _FakeRawItem:
    text: str = ""
    name: str = ""
    arguments: str = "{}"
    call_id: str = "call_123"
    output: str = ""


@dataclass
class _FakeItem:
    raw_item: Any = None


@dataclass
class _FakeRunItemEvent:
    type: str = "run_item_stream_event"
    name: str = ""
    item: Any = None


@dataclass
class _FakeRawDelta:
    type: str = "response.output_text.delta"
    delta: str = ""


@dataclass
class _FakeRawResponseEvent:
    type: str = "raw_response_stream_event"
    data: Any = None


class _FakeStreamResult:
    def __init__(
        self,
        events: list[Any] | None = None,
        usage: Any = None,
        on_event: Any = None,
    ) -> None:
        self._events = list(events or [])
        self._on_event = on_event
        self.final_output = None
        self.context_wrapper = types.SimpleNamespace(usage=usage)

    async def stream_events(self) -> AsyncIterator[Any]:
        for index, event in enumerate(self._events):
            if self._on_event is not None:
                self._on_event(index)
            yield event


class _FakeOaiAgent:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs


class _FakeChatModel:
    def __init__(self, model: str, openai_client: Any) -> None:
        self.model = model
        self.openai_client = openai_client


def _install_fake_agents_module(
    monkeypatch: pytest.MonkeyPatch, result: _FakeStreamResult
) -> None:
    class _Runner:
        @staticmethod
        def run_streamed(**kwargs: Any) -> _FakeStreamResult:
            return result

    fake_agents = types.SimpleNamespace(
        Agent=_FakeOaiAgent,
        Runner=_Runner,
        OpenAIChatCompletionsModel=_FakeChatModel,
    )
    monkeypatch.setitem(sys.modules, "agents", fake_agents)


async def _collect_openai(
    monkeypatch: pytest.MonkeyPatch, result: _FakeStreamResult
) -> tuple[Any, list[RuntimeEvent]]:
    from swarmline.runtime.openai_agents.runtime import OpenAIAgentsRuntime

    _install_fake_agents_module(monkeypatch, result)
    runtime = OpenAIAgentsRuntime(
        config=RuntimeConfig(runtime_name="openai_agents", model="gpt-4.1")
    )
    events: list[RuntimeEvent] = []
    async for event in runtime.run(
        messages=list(_USER_MESSAGES), system_prompt="sys", active_tools=[]
    ):
        events.append(event)
    return runtime, events


class _OpenAIAgentsDriver:
    @staticmethod
    async def stream_text(monkeypatch: pytest.MonkeyPatch) -> list[RuntimeEvent]:
        result = _FakeStreamResult(
            events=[
                _FakeRawResponseEvent(data=_FakeRawDelta(delta="Hello ")),
                _FakeRawResponseEvent(data=_FakeRawDelta(delta="world")),
            ]
        )
        _, events = await _collect_openai(monkeypatch, result)
        return events

    new_messages = stream_text

    @staticmethod
    async def thinking(monkeypatch: pytest.MonkeyPatch) -> list[RuntimeEvent]:
        result = _FakeStreamResult(
            events=[
                _FakeRawResponseEvent(
                    data=_FakeRawDelta(
                        type="response.reasoning_summary_text.delta",
                        delta="pondering",
                    )
                ),
                _FakeRawResponseEvent(data=_FakeRawDelta(delta="answer")),
            ]
        )
        _, events = await _collect_openai(monkeypatch, result)
        return events

    @staticmethod
    async def usage(monkeypatch: pytest.MonkeyPatch) -> list[RuntimeEvent]:
        usage = types.SimpleNamespace(
            input_tokens=11, output_tokens=7, total_tokens=18, requests=1
        )
        result = _FakeStreamResult(
            events=[_FakeRawResponseEvent(data=_FakeRawDelta(delta="answer"))],
            usage=usage,
        )
        _, events = await _collect_openai(monkeypatch, result)
        return events

    @staticmethod
    async def cancellation(monkeypatch: pytest.MonkeyPatch) -> list[RuntimeEvent]:
        from swarmline.runtime.openai_agents.runtime import OpenAIAgentsRuntime

        runtime_box: list[Any] = []

        def _on_event(index: int) -> None:
            if index == 1:  # cancel after the first event was consumed
                runtime_box[0].cancel()

        result = _FakeStreamResult(
            events=[
                _FakeRawResponseEvent(data=_FakeRawDelta(delta="part1")),
                _FakeRawResponseEvent(data=_FakeRawDelta(delta="part2")),
            ],
            on_event=_on_event,
        )
        _install_fake_agents_module(monkeypatch, result)
        runtime = OpenAIAgentsRuntime(
            config=RuntimeConfig(runtime_name="openai_agents", model="gpt-4.1")
        )
        runtime_box.append(runtime)
        events: list[RuntimeEvent] = []
        async for event in runtime.run(
            messages=list(_USER_MESSAGES), system_prompt="sys", active_tools=[]
        ):
            events.append(event)
        return events

    @staticmethod
    async def tool_calls(monkeypatch: pytest.MonkeyPatch) -> list[RuntimeEvent]:
        result = _FakeStreamResult(
            events=[
                _FakeRunItemEvent(
                    name="tool_called",
                    item=_FakeItem(
                        raw_item=_FakeRawItem(
                            name="calc", arguments='{"x": 1}', call_id="c1"
                        )
                    ),
                ),
                _FakeRunItemEvent(
                    name="tool_output",
                    item=_FakeItem(
                        raw_item=_FakeRawItem(output='{"result": 2}', call_id="c1")
                    ),
                ),
                _FakeRawResponseEvent(data=_FakeRawDelta(delta="done")),
            ]
        )
        _, events = await _collect_openai(monkeypatch, result)
        return events


# ---------------------------------------------------------------------------
# pi_sdk driver — fake Node bridge process
# (tests/unit/test_pi_sdk_runtime.py seam)
# ---------------------------------------------------------------------------


def _pi_runtime(**kwargs: Any) -> Any:
    from swarmline.runtime.pi_sdk import PiSdkOptions
    from swarmline.runtime.pi_sdk.runtime import PiSdkRuntime

    return PiSdkRuntime(
        config=RuntimeConfig(runtime_name="pi_sdk"),
        pi_options=PiSdkOptions(bridge_command=("fake-pi-bridge",)),
        **kwargs,
    )


def _pi_lines(payloads: list[dict[str, Any]]) -> bytes:
    return b"\n".join(json.dumps(p).encode() for p in payloads) + b"\n"


async def _collect_pi(
    runtime: Any,
    stdout_data: bytes,
    *,
    active_tools: list[ToolSpec] | None = None,
) -> list[RuntimeEvent]:
    process = _make_cli_process(stdout_data)
    events: list[RuntimeEvent] = []
    with patch("asyncio.create_subprocess_exec", return_value=process):
        async for event in runtime.run(
            messages=list(_USER_MESSAGES),
            system_prompt="sys",
            active_tools=active_tools or [],
        ):
            events.append(event)
    return events


class _PiSdkDriver:
    @staticmethod
    async def stream_text() -> list[RuntimeEvent]:
        return await _collect_pi(
            _pi_runtime(),
            _pi_lines(
                [
                    {"type": "assistant_delta", "text": "Hello "},
                    {"type": "assistant_delta", "text": "world"},
                    {"type": "final", "text": "Hello world"},
                ]
            ),
        )

    @staticmethod
    async def new_messages() -> list[RuntimeEvent]:
        return await _collect_pi(
            _pi_runtime(),
            _pi_lines(
                [
                    {"type": "assistant_delta", "text": "done"},
                    {
                        "type": "final",
                        "text": "done",
                        "new_messages": [{"role": "assistant", "content": "done"}],
                    },
                ]
            ),
        )

    @staticmethod
    async def thinking() -> list[RuntimeEvent]:
        return await _collect_pi(
            _pi_runtime(),
            _pi_lines(
                [
                    {"type": "thinking_delta", "text": "pondering"},
                    {"type": "final", "text": "done"},
                ]
            ),
        )

    @staticmethod
    async def usage() -> list[RuntimeEvent]:
        return await _collect_pi(
            _pi_runtime(),
            _pi_lines(
                [
                    {
                        "type": "final",
                        "text": "done",
                        "usage": {"input_tokens": 120, "output_tokens": 45},
                        "total_cost_usd": 0.0123,
                    }
                ]
            ),
        )

    @staticmethod
    async def cancellation() -> list[RuntimeEvent]:
        runtime = _pi_runtime()

        line1 = json.dumps({"type": "assistant_delta", "text": "part1"}).encode()
        line2 = json.dumps({"type": "assistant_delta", "text": "part2"}).encode()

        async def _stdout_iter() -> AsyncIterator[bytes]:
            yield line1 + b"\n"
            runtime.cancel()
            yield line2 + b"\n"

        process = _make_cli_process(b"")
        process.stdout = _stdout_iter()

        events: list[RuntimeEvent] = []
        with patch("asyncio.create_subprocess_exec", return_value=process):
            async for event in runtime.run(
                messages=list(_USER_MESSAGES), system_prompt="sys", active_tools=[]
            ):
                events.append(event)
        return events

    @staticmethod
    async def tool_calls() -> list[RuntimeEvent]:
        async def calc(x: int) -> str:
            return str(x + 1)

        runtime = _pi_runtime(tool_executors={"calc": calc})
        tools = [
            ToolSpec(
                name="calc",
                description="calc",
                parameters={"type": "object"},
                is_local=True,
            )
        ]
        return await _collect_pi(
            runtime,
            _pi_lines(
                [
                    {
                        "type": "tool_request",
                        "id": "req-1",
                        "name": "calc",
                        "args": {"x": 1},
                    },
                    {"type": "final", "text": "done"},
                ]
            ),
            active_tools=tools,
        )


_DRIVERS: dict[str, Any] = {
    "thin": _ThinDriver,
    "claude_sdk": _ClaudeSdkDriver,
    "deepagents": _DeepAgentsDriver,
    "cli": _CliDriver,
    "openai_agents": _OpenAIAgentsDriver,
    "pi_sdk": _PiSdkDriver,
}


async def _drive(
    runtime: str, scenario: str, monkeypatch: pytest.MonkeyPatch
) -> list[RuntimeEvent]:
    driver = getattr(_DRIVERS[runtime], scenario)
    if runtime == "openai_agents":
        return await driver(monkeypatch)
    return await driver()


# ---------------------------------------------------------------------------
# Scenario 1: streaming text + exactly one final
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("runtime", RUNTIMES)
async def test_stream_text_and_single_final(
    runtime: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = await _drive(runtime, "stream_text", monkeypatch)

    deltas = [e for e in events if e.type == "assistant_delta"]
    finals = _finals(events)
    assert len(deltas) >= 1, f"{runtime}: no assistant_delta events: {events}"
    assert len(finals) == 1, f"{runtime}: expected exactly one final: {events}"
    assert not any(e.type == "error" for e in events)
    # Where the runtime emits both, the final text equals the delta stream.
    expected = "Hello streamed world" if runtime == "thin" else "Hello world"
    assert finals[0].data["text"] == _delta_text(events) == expected


# ---------------------------------------------------------------------------
# Scenario 2: final carries new_messages with the assistant reply
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("runtime", RUNTIMES)
async def test_final_carries_new_messages(
    runtime: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = await _drive(runtime, "new_messages", monkeypatch)

    finals = _finals(events)
    assert len(finals) == 1
    new_messages = finals[0].data.get("new_messages")
    assert new_messages, f"{runtime}: final carries no new_messages: {finals[0].data}"

    def _role(message: Any) -> str:
        if isinstance(message, dict):
            return str(message.get("role", ""))
        return str(getattr(message, "role", ""))

    assert any(_role(m) == "assistant" for m in new_messages), (
        f"{runtime}: no assistant message in new_messages: {new_messages}"
    )


# ---------------------------------------------------------------------------
# Scenario 3: thinking_delta emitted (thinking_stream != none)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("runtime", RUNTIMES)
async def test_thinking_delta_emitted(
    runtime: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _skip_if_capability_none(runtime, "thinking_stream")
    events = await _drive(runtime, "thinking", monkeypatch)

    thinking = [e for e in events if e.type == "thinking_delta"]
    assert len(thinking) >= 1, f"{runtime}: no thinking_delta events: {events}"
    assert thinking[0].data["text"], f"{runtime}: empty thinking text"
    assert len(_finals(events)) == 1


# ---------------------------------------------------------------------------
# Scenario 4: usage reported on final (usage_reporting != none)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("runtime", RUNTIMES)
async def test_usage_reported(runtime: str, monkeypatch: pytest.MonkeyPatch) -> None:
    _skip_if_capability_none(runtime, "usage_reporting")
    events = await _drive(runtime, "usage", monkeypatch)

    finals = _finals(events)
    assert len(finals) == 1
    usage = finals[0].data.get("usage")
    assert usage, f"{runtime}: final carries no usage: {finals[0].data}"
    assert int(usage["input_tokens"]) > 0
    assert int(usage["output_tokens"]) > 0
    # Cross-check metrics only when the runtime mirrors usage into metrics.
    # Known gap: claude_sdk carries usage on final.data["usage"] but leaves
    # metrics.tokens_in/out at 0 (thin/deepagents/openai_agents/pi_sdk mirror).
    metrics = finals[0].data.get("metrics") or {}
    if metrics and int(metrics.get("tokens_in", 0)) > 0:
        assert int(metrics["tokens_in"]) == int(usage["input_tokens"])


# ---------------------------------------------------------------------------
# Scenario 5: cancellation mid-stream (interrupt != none)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("runtime", RUNTIMES)
async def test_cancellation(runtime: str, monkeypatch: pytest.MonkeyPatch) -> None:
    _skip_if_capability_none(runtime, "interrupt")
    events = await _drive(runtime, "cancellation", monkeypatch)

    cancelled = [
        e for e in events if e.type == "error" and e.data.get("kind") == "cancelled"
    ]
    assert len(cancelled) == 1, (
        f"{runtime}: expected one cancelled error event: {events}"
    )
    assert not _finals(events), f"{runtime}: final emitted after cancellation"
    # The cancelled error must terminate the stream.
    assert events[-1].type == "error"


# ---------------------------------------------------------------------------
# Scenario 6: tool call events with matching correlation ids
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("runtime", RUNTIMES)
async def test_tool_call_events(runtime: str, monkeypatch: pytest.MonkeyPatch) -> None:
    if runtime == "cli":
        pytest.skip(
            "cli: no custom local-tool seam (subprocess owns its own tools); "
            "the declared matrix exposes no tool dimension for cli"
        )
    events = await _drive(runtime, "tool_calls", monkeypatch)

    started = [e for e in events if e.type == "tool_call_started"]
    finished = [e for e in events if e.type == "tool_call_finished"]
    assert len(started) == 1, f"{runtime}: expected one tool_call_started: {events}"
    assert len(finished) == 1, f"{runtime}: expected one tool_call_finished: {events}"
    assert started[0].data["name"] == "calc"
    assert started[0].data["correlation_id"] == finished[0].data["correlation_id"]
    assert finished[0].data["ok"] is True
    assert len(_finals(events)) == 1
