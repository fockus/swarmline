"""Tests for shared agent runtime dispatch helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

pytest.importorskip(
    "claude_agent_sdk",
    reason="claude-agent-sdk not installed (pip install swarmline[claude])",
)

pytestmark = pytest.mark.requires_claude_sdk

from swarmline.agent.config import AgentConfig  # noqa: E402
from swarmline.agent.runtime_dispatch import (  # noqa: E402
    create_claude_conversation_adapter,
    stream_claude_one_shot,
)


class _Factory:
    def validate_agent_config(self, config: AgentConfig) -> None:
        _ = config

    def resolve_agent_model(self, config: AgentConfig) -> str:
        return config.model


async def _failing_stream(*args: Any, **kwargs: Any) -> AsyncIterator[Any]:
    _ = (args, kwargs)
    raise RuntimeError(
        "upstream failed Authorization: Bearer claude-dispatch-secret-1234567890"
    )
    yield object()


class TestStreamClaudeOneShot:
    async def test_stream_error_redacts_secret_in_event_and_logs(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        secret = "claude-dispatch-secret-1234567890"
        monkeypatch.setattr(
            "swarmline.runtime.sdk_query.stream_one_shot_query",
            _failing_stream,
        )

        caplog.set_level("ERROR", logger="swarmline.agent.runtime_dispatch")
        events = [
            event
            async for event in stream_claude_one_shot(
                "hi",
                AgentConfig(system_prompt="test", model="sonnet"),
                runtime_factory=_Factory(),
            )
        ]

        assert len(events) == 1
        assert events[0].type == "error"
        assert secret not in events[0].text
        assert "RuntimeError" in events[0].text
        assert secret not in caplog.text


async def _noop_can_use_tool(
    tool_name: str,
    input_data: dict[str, Any],
    context: Any,
) -> Any:
    _ = (tool_name, input_data, context)
    return {"behavior": "allow"}


class _FakeBuilder:
    """Captures ClaudeOptionsBuilder.build kwargs."""

    last_build_kwargs: dict[str, Any] = {}

    def __init__(self, **kwargs: Any) -> None:
        _ = kwargs

    def build(self, **kwargs: Any) -> Any:
        _FakeBuilder.last_build_kwargs = kwargs
        return object()


class _FakeAdapter:
    """RuntimeAdapter stand-in with a no-op connect."""

    def __init__(self, opts: Any) -> None:
        self.opts = opts
        self.connected = False

    async def connect(self) -> None:
        self.connected = True


@pytest.fixture
def patched_adapter_deps(monkeypatch: pytest.MonkeyPatch) -> type[_FakeBuilder]:
    _FakeBuilder.last_build_kwargs = {}
    monkeypatch.setattr(
        "swarmline.runtime.options_builder.ClaudeOptionsBuilder",
        _FakeBuilder,
    )
    monkeypatch.setattr("swarmline.runtime.adapter.RuntimeAdapter", _FakeAdapter)
    return _FakeBuilder


class TestCreateClaudeConversationAdapter:
    async def test_passes_can_use_tool_agents_resume_to_builder(
        self,
        patched_adapter_deps: type[_FakeBuilder],
    ) -> None:
        native_agents = {"helper": {"description": "d", "prompt": "p"}}
        config = AgentConfig(
            system_prompt="test",
            runtime="claude_sdk",
            permission_mode="default",
            can_use_tool=_noop_can_use_tool,
            native_agents=native_agents,
            resume_session_id="sess-123",
            fork_session=True,
        )

        adapter = await create_claude_conversation_adapter(
            config,
            runtime_factory=_Factory(),
        )

        assert isinstance(adapter, _FakeAdapter)
        assert adapter.connected
        kwargs = patched_adapter_deps.last_build_kwargs
        assert kwargs["can_use_tool"] is _noop_can_use_tool
        assert kwargs["agents"] == native_agents
        assert kwargs["resume"] == "sess-123"
        assert kwargs["fork_session"] is True
        # resume-by-id must not force continue-latest-conversation
        assert kwargs["continue_conversation"] is False

    async def test_defaults_keep_continue_conversation_true(
        self,
        patched_adapter_deps: type[_FakeBuilder],
    ) -> None:
        config = AgentConfig(system_prompt="test", runtime="claude_sdk")

        await create_claude_conversation_adapter(config, runtime_factory=_Factory())

        kwargs = patched_adapter_deps.last_build_kwargs
        assert kwargs["continue_conversation"] is True
        assert kwargs["resume"] is None
        assert kwargs["fork_session"] is False
        assert kwargs["can_use_tool"] is None
        assert kwargs["agents"] is None

    async def test_can_use_tool_with_bypass_permissions_raises(
        self,
        patched_adapter_deps: type[_FakeBuilder],
    ) -> None:
        config = AgentConfig(
            system_prompt="test",
            runtime="claude_sdk",
            can_use_tool=_noop_can_use_tool,
            # default permission_mode is "bypassPermissions"
        )

        with pytest.raises(ValueError, match="bypassPermissions"):
            await create_claude_conversation_adapter(
                config,
                runtime_factory=_Factory(),
            )

    async def test_tool_policy_adapted_to_sdk_callback(
        self,
        patched_adapter_deps: type[_FakeBuilder],
    ) -> None:
        from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

        from swarmline.policy.tool_policy import DefaultToolPolicy

        config = AgentConfig(
            system_prompt="test",
            runtime="claude_sdk",
            permission_mode="default",
            tool_policy=DefaultToolPolicy(),
            mcp_servers={"iss": {"type": "http", "url": "http://iss.test"}},
        )

        await create_claude_conversation_adapter(config, runtime_factory=_Factory())

        callback = patched_adapter_deps.last_build_kwargs["can_use_tool"]
        assert callback is not None

        denied = await callback("Bash", {"command": "ls"}, None)
        assert isinstance(denied, PermissionResultDeny)
        assert denied.behavior == "deny"
        assert denied.message

        allowed = await callback("mcp__iss__get_position", {}, None)
        assert isinstance(allowed, PermissionResultAllow)
        assert allowed.behavior == "allow"

    async def test_tool_policy_skipped_under_bypass_permissions(
        self,
        patched_adapter_deps: type[_FakeBuilder],
    ) -> None:
        from swarmline.policy.tool_policy import DefaultToolPolicy

        config = AgentConfig(
            system_prompt="test",
            runtime="claude_sdk",
            tool_policy=DefaultToolPolicy(),
        )

        await create_claude_conversation_adapter(config, runtime_factory=_Factory())

        assert patched_adapter_deps.last_build_kwargs["can_use_tool"] is None


class TestStreamClaudeOneShotNativeWiring:
    async def test_passes_can_use_tool_and_agents(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, Any] = {}

        async def fake_stream(prompt: str, **kwargs: Any) -> AsyncIterator[Any]:
            captured["prompt"] = prompt
            captured.update(kwargs)
            return
            yield object()

        monkeypatch.setattr(
            "swarmline.runtime.sdk_query.stream_one_shot_query",
            fake_stream,
        )

        native_agents = {"helper": {"description": "d", "prompt": "p"}}
        config = AgentConfig(
            system_prompt="test",
            runtime="claude_sdk",
            permission_mode="default",
            can_use_tool=_noop_can_use_tool,
            native_agents=native_agents,
        )

        events = [
            event
            async for event in stream_claude_one_shot(
                "hi",
                config,
                runtime_factory=_Factory(),
            )
        ]

        assert events == []
        assert captured["can_use_tool"] is _noop_can_use_tool
        assert captured["agents"] == native_agents

    async def test_can_use_tool_with_bypass_permissions_raises(self) -> None:
        config = AgentConfig(
            system_prompt="test",
            runtime="claude_sdk",
            can_use_tool=_noop_can_use_tool,
        )

        with pytest.raises(ValueError, match="bypassPermissions"):
            async for _ in stream_claude_one_shot(
                "hi",
                config,
                runtime_factory=_Factory(),
            ):
                pass


class TestStreamClaudeOneShotParity:
    """I-099 — the one-shot dispatch path must forward the same
    thinking/sandbox/max_thinking_tokens/output_format-from-output_type
    behavior as the conversation path (create_claude_conversation_adapter)."""

    @staticmethod
    def _patched_stream(
        monkeypatch: pytest.MonkeyPatch, captured: dict[str, Any]
    ) -> None:
        async def fake_stream(prompt: str, **kwargs: Any) -> AsyncIterator[Any]:
            captured["prompt"] = prompt
            captured.update(kwargs)
            return
            yield object()

        monkeypatch.setattr(
            "swarmline.runtime.sdk_query.stream_one_shot_query",
            fake_stream,
        )

    async def test_forwards_thinking_sandbox_max_thinking_tokens(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from swarmline.runtime.types import ThinkingConfig

        captured: dict[str, Any] = {}
        self._patched_stream(monkeypatch, captured)

        config = AgentConfig(
            system_prompt="test",
            runtime="claude_sdk",
            thinking=ThinkingConfig(budget_tokens=4096),
            sandbox={"enabled": True},
            max_thinking_tokens=2048,
        )

        events = [
            event
            async for event in stream_claude_one_shot(
                "hi", config, runtime_factory=_Factory()
            )
        ]

        assert events == []
        assert captured["thinking"] == {"type": "enabled", "budget_tokens": 4096}
        assert captured["sandbox"] == {"enabled": True}
        assert captured["max_thinking_tokens"] == 2048

    async def test_output_type_only_derives_output_format_like_query_structured(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from pydantic import BaseModel

        class Answer(BaseModel):
            text: str

        captured: dict[str, Any] = {}
        self._patched_stream(monkeypatch, captured)

        config = AgentConfig(
            system_prompt="test",
            runtime="claude_sdk",
            output_type=Answer,
        )

        async for _ in stream_claude_one_shot("hi", config, runtime_factory=_Factory()):
            pass

        assert captured["output_format"] == Answer.model_json_schema()

    async def test_output_format_wins_over_output_type_when_both_set(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from pydantic import BaseModel

        class Answer(BaseModel):
            text: str

        explicit_format = {"type": "object", "properties": {"custom": {}}}

        captured: dict[str, Any] = {}
        self._patched_stream(monkeypatch, captured)

        config = AgentConfig(
            system_prompt="test",
            runtime="claude_sdk",
            output_type=Answer,
            output_format=explicit_format,
        )

        async for _ in stream_claude_one_shot("hi", config, runtime_factory=_Factory()):
            pass

        assert captured["output_format"] == explicit_format

    async def test_kwargs_are_superset_of_parity_critical_set(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Anti-drift contract (I-099): if this shrinks, the two claude_sdk
        dispatch paths have silently diverged again."""
        captured: dict[str, Any] = {}
        self._patched_stream(monkeypatch, captured)

        config = AgentConfig(system_prompt="test", runtime="claude_sdk")

        async for _ in stream_claude_one_shot("hi", config, runtime_factory=_Factory()):
            pass

        parity_critical = {
            "thinking",
            "sandbox",
            "max_thinking_tokens",
            "resume",
            "fork_session",
            "can_use_tool",
            "agents",
        }
        assert parity_critical <= captured.keys()


class TestCreateClaudeConversationAdapterOutputFormat:
    """I-099 review finding 1 — create_claude_conversation_adapter must derive
    output_format from output_type exactly like stream_claude_one_shot does
    (both call _effective_output_format); a raw config.output_format
    passthrough would re-invert the asymmetry the parity fix set out to
    remove."""

    async def test_output_type_only_derives_output_format(
        self,
        patched_adapter_deps: type[_FakeBuilder],
    ) -> None:
        from pydantic import BaseModel

        class Answer(BaseModel):
            text: str

        config = AgentConfig(
            system_prompt="test",
            runtime="claude_sdk",
            output_type=Answer,
        )

        await create_claude_conversation_adapter(config, runtime_factory=_Factory())

        kwargs = patched_adapter_deps.last_build_kwargs
        assert kwargs["output_format"] == Answer.model_json_schema()

    async def test_explicit_output_format_wins_over_output_type(
        self,
        patched_adapter_deps: type[_FakeBuilder],
    ) -> None:
        from pydantic import BaseModel

        class Answer(BaseModel):
            text: str

        explicit_format = {"type": "object", "properties": {"custom": {}}}
        config = AgentConfig(
            system_prompt="test",
            runtime="claude_sdk",
            output_type=Answer,
            output_format=explicit_format,
        )

        await create_claude_conversation_adapter(config, runtime_factory=_Factory())

        kwargs = patched_adapter_deps.last_build_kwargs
        assert kwargs["output_format"] == explicit_format

    async def test_no_output_type_or_format_stays_none(
        self,
        patched_adapter_deps: type[_FakeBuilder],
    ) -> None:
        config = AgentConfig(system_prompt="test", runtime="claude_sdk")

        await create_claude_conversation_adapter(config, runtime_factory=_Factory())

        assert patched_adapter_deps.last_build_kwargs["output_format"] is None


class TestBothClaudeSdkPathsOutputFormatParity:
    """I-099 review finding 1 — for a single AgentConfig, the one-shot path
    (stream_claude_one_shot -> stream_one_shot_query) and the conversation
    path (create_claude_conversation_adapter -> ClaudeOptionsBuilder.build)
    must derive the identical output_format, both for output_type-only
    configs and for the explicit-output_format-wins case."""

    @staticmethod
    def _patched_one_shot(
        monkeypatch: pytest.MonkeyPatch, captured: dict[str, Any]
    ) -> None:
        async def fake_stream(prompt: str, **kwargs: Any) -> AsyncIterator[Any]:
            captured.update(kwargs)
            return
            yield object()

        monkeypatch.setattr(
            "swarmline.runtime.sdk_query.stream_one_shot_query",
            fake_stream,
        )

    async def test_output_type_only_matches_across_both_paths(
        self,
        monkeypatch: pytest.MonkeyPatch,
        patched_adapter_deps: type[_FakeBuilder],
    ) -> None:
        from pydantic import BaseModel

        class Answer(BaseModel):
            text: str

        config = AgentConfig(
            system_prompt="test",
            runtime="claude_sdk",
            output_type=Answer,
        )

        one_shot_captured: dict[str, Any] = {}
        self._patched_one_shot(monkeypatch, one_shot_captured)

        async for _ in stream_claude_one_shot("hi", config, runtime_factory=_Factory()):
            pass
        await create_claude_conversation_adapter(config, runtime_factory=_Factory())

        conversation_output_format = patched_adapter_deps.last_build_kwargs[
            "output_format"
        ]
        assert one_shot_captured["output_format"] == conversation_output_format
        assert conversation_output_format == Answer.model_json_schema()

    async def test_explicit_output_format_wins_identically_across_both_paths(
        self,
        monkeypatch: pytest.MonkeyPatch,
        patched_adapter_deps: type[_FakeBuilder],
    ) -> None:
        from pydantic import BaseModel

        class Answer(BaseModel):
            text: str

        explicit_format = {"type": "object", "properties": {"custom": {}}}
        config = AgentConfig(
            system_prompt="test",
            runtime="claude_sdk",
            output_type=Answer,
            output_format=explicit_format,
        )

        one_shot_captured: dict[str, Any] = {}
        self._patched_one_shot(monkeypatch, one_shot_captured)

        async for _ in stream_claude_one_shot("hi", config, runtime_factory=_Factory()):
            pass
        await create_claude_conversation_adapter(config, runtime_factory=_Factory())

        conversation_output_format = patched_adapter_deps.last_build_kwargs[
            "output_format"
        ]
        assert one_shot_captured["output_format"] == conversation_output_format
        assert conversation_output_format == explicit_format


class TestEffectiveOutputFormatLoudFailure:
    """I-099 review finding 2 — an unsupported (non-Pydantic) output_type must
    fail loud and named on every claude_sdk dispatch path, not surface as a
    bare AttributeError (or silently resolve to output_format=None). Note:
    pi_sdk/cli already fail loud via a separate, pre-existing guard
    (RuntimeConfig.__post_init__ in runtime/types.py, TypeError) that fires
    before run_portable_runtime ever reaches _effective_output_format — see
    TestDispatchStructuredOutput.test_pi_sdk_unsupported_output_type_already_fails_loud_pre_existing.
    Only claude_sdk (one-shot + conversation) lacked a guard before this fix."""

    async def test_one_shot_surfaces_named_value_error_as_error_event(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        reached: dict[str, Any] = {}

        async def fake_stream(prompt: str, **kwargs: Any) -> AsyncIterator[Any]:
            reached.update(kwargs)
            return
            yield object()

        monkeypatch.setattr(
            "swarmline.runtime.sdk_query.stream_one_shot_query",
            fake_stream,
        )

        config = AgentConfig(
            system_prompt="test", runtime="claude_sdk", output_type=dict
        )

        events = [
            event
            async for event in stream_claude_one_shot(
                "hi", config, runtime_factory=_Factory()
            )
        ]

        assert len(events) == 1
        assert events[0].type == "error"
        assert "output_type must be a Pydantic BaseModel" in events[0].text
        assert "ValueError" in events[0].text
        # never reached stream_one_shot_query: the failure happens while
        # building the kwargs, before the SDK call.
        assert reached == {}

    async def test_conversation_path_raises_named_value_error(
        self,
        patched_adapter_deps: type[_FakeBuilder],
    ) -> None:
        config = AgentConfig(
            system_prompt="test", runtime="claude_sdk", output_type=dict
        )

        with pytest.raises(
            ValueError, match="output_type must be a Pydantic BaseModel"
        ):
            await create_claude_conversation_adapter(config, runtime_factory=_Factory())

    async def test_pydantic_output_type_still_derives_schema_on_one_shot_path(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from pydantic import BaseModel

        class Answer(BaseModel):
            text: str

        captured: dict[str, Any] = {}

        async def fake_stream(prompt: str, **kwargs: Any) -> AsyncIterator[Any]:
            captured.update(kwargs)
            return
            yield object()

        monkeypatch.setattr(
            "swarmline.runtime.sdk_query.stream_one_shot_query",
            fake_stream,
        )

        config = AgentConfig(
            system_prompt="test", runtime="claude_sdk", output_type=Answer
        )

        async for _ in stream_claude_one_shot("hi", config, runtime_factory=_Factory()):
            pass

        assert captured["output_format"] == Answer.model_json_schema()


class TestStreamOneShotQueryStreamingInput:
    async def test_can_use_tool_wraps_prompt_into_streaming_input(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from swarmline.runtime import sdk_query

        captured: dict[str, Any] = {}

        async def fake_sdk_query(*, prompt: Any, options: Any) -> AsyncIterator[Any]:
            captured["prompt"] = prompt
            captured["options"] = options
            return
            yield object()

        monkeypatch.setattr(sdk_query, "_sdk_query", fake_sdk_query)

        events = [
            event
            async for event in sdk_query.stream_one_shot_query(
                "hi",
                can_use_tool=_noop_can_use_tool,
            )
        ]

        # No ResultMessage from the fake -> single error event; the point of
        # this test is the prompt shape, which must be an async iterable.
        assert [e.type for e in events] == ["error"]
        assert not isinstance(captured["prompt"], str)
        messages = [m async for m in captured["prompt"]]
        assert messages == [
            {"type": "user", "message": {"role": "user", "content": "hi"}}
        ]
        assert captured["options"].can_use_tool is _noop_can_use_tool

    async def test_plain_prompt_stays_string_without_can_use_tool(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from swarmline.runtime import sdk_query

        captured: dict[str, Any] = {}

        async def fake_sdk_query(*, prompt: Any, options: Any) -> AsyncIterator[Any]:
            captured["prompt"] = prompt
            return
            yield object()

        monkeypatch.setattr(sdk_query, "_sdk_query", fake_sdk_query)

        async for _ in sdk_query.stream_one_shot_query("hi"):
            pass

        assert captured["prompt"] == "hi"


class TestDispatchStructuredOutput:
    """Plan D1: dispatch-layer structured output for pi_sdk/cli."""

    @staticmethod
    def _run(agent_config, runtime_name, final_text):
        import asyncio

        from unittest.mock import MagicMock

        from swarmline.agent.runtime_dispatch import run_portable_runtime
        from swarmline.runtime.types import RuntimeEvent

        captured: dict[str, object] = {}

        class FakeRuntime:
            async def run(self, *, messages, system_prompt, active_tools):
                captured["system_prompt"] = system_prompt
                yield RuntimeEvent.final(final_text)

            async def cleanup(self) -> None:
                return None

        fake_factory = MagicMock()
        fake_factory.create.return_value = FakeRuntime()

        async def _drive():
            events = []
            async for event in run_portable_runtime(
                agent_config,
                runtime_name,
                messages=[],
                system_prompt="base prompt",
                runtime_factory=fake_factory,
                event_adapter=lambda e: e,
                error_factory=lambda exc: exc,
                logger=__import__("logging").getLogger("test"),
                error_context="test",
            ):
                events.append(event)
            return events

        events = asyncio.get_event_loop().run_until_complete(_drive())
        return captured, events

    def test_pi_sdk_gets_schema_instruction_and_parsed_output(self) -> None:
        import asyncio

        from swarmline.agent.config import AgentConfig

        config = AgentConfig(
            system_prompt="base prompt",
            runtime="pi_sdk",
            output_format={
                "type": "object",
                "properties": {"answer": {"type": "string"}},
            },
        )
        asyncio.set_event_loop(asyncio.new_event_loop())
        captured, events = self._run(config, "pi_sdk", '{"answer": "42"}')

        assert "base prompt" in captured["system_prompt"]
        assert "answer" in captured["system_prompt"]  # schema injected
        final = events[-1]
        assert final.type == "final"
        assert final.data["structured_output"] == {"answer": "42"}

    def test_cli_gets_structured_output_from_fenced_json(self) -> None:
        import asyncio

        from swarmline.agent.config import AgentConfig

        config = AgentConfig(
            system_prompt="base prompt",
            runtime="cli",
            output_format={
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
            },
        )
        asyncio.set_event_loop(asyncio.new_event_loop())
        captured, events = self._run(
            config, "cli", 'Result:\n```json\n{"ok": true}\n```'
        )
        assert events[-1].data["structured_output"] == {"ok": True}

    def test_thin_is_untouched_by_dispatch_emulation(self) -> None:
        import asyncio

        from swarmline.agent.config import AgentConfig

        config = AgentConfig(
            system_prompt="base prompt",
            runtime="thin",
            output_format={
                "type": "object",
                "properties": {"x": {"type": "integer"}},
            },
        )
        asyncio.set_event_loop(asyncio.new_event_loop())
        captured, events = self._run(config, "thin", '{"x": 1}')

        # thin handles structured output inside the runtime; the dispatch
        # layer must not inject the schema a second time
        assert captured["system_prompt"] == "base prompt"
        assert events[-1].data.get("structured_output") is None

    def test_pi_sdk_unsupported_output_type_already_fails_loud_pre_existing(
        self,
    ) -> None:
        """I-099 review finding 2 investigation result: pi_sdk/cli do NOT reach
        extract_pydantic_schema's bare AttributeError for an output_type-only
        config, contrary to the review's working assumption. build_portable_
        runtime_plan constructs a RuntimeConfig from the same AgentConfig
        BEFORE run_portable_runtime ever calls _effective_output_format, and
        RuntimeConfig.__post_init__ (runtime/types.py) already has its own
        pre-existing loud-over-silent guard
        (``TypeError: output_type must define model_json_schema()``) — a
        different exception type/message than the new extract_pydantic_schema
        ValueError, but already loud, not a bare AttributeError. This test
        pins that PRE-EXISTING behavior: Stage 3's fix does not need to (and
        does not) touch runtime/types.py to make pi_sdk/cli loud — only the
        claude_sdk one-shot/conversation paths lacked a guard before this fix,
        because AgentConfig.__post_init__ has no equivalent check."""
        import asyncio

        from swarmline.agent.config import AgentConfig

        config = AgentConfig(
            system_prompt="base prompt",
            runtime="pi_sdk",
            output_type=dict,
        )
        asyncio.set_event_loop(asyncio.new_event_loop())
        with pytest.raises(
            TypeError, match="output_type must define model_json_schema"
        ):
            self._run(config, "pi_sdk", "irrelevant")
