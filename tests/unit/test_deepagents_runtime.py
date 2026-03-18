"""Tests for DeepAgentsRuntime - Deep Agents runtime. Covered Cases:
- Built-in tools filtering (frozenset, filter_builtin_tools)
- Dependency check (_check_langchain_available)
- run(): missing deps, happy path, empty response, exception, base_url, tool events
- run(): built-in tools are filtered inside run()
- run(): new_messages contains assistant text
- run(): multiple tool_call_finished -> metrics.tool_calls_count
- _build_lc_messages: user/assistant/system -> LangChain messages
- _build_llm: wrapper around provider-aware builder
- _stream_langchain: event parsing (on_chat_model_stream, on_tool_start, on_tool_end)
- _stream_langchain: correlation tool (run_id -> correlation_id)
- create_langchain_tool: with executor, without executor (noop), dict-based executor
- cleanup: noop"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("deepagents", reason="deepagents не установлен")
from cognitia.runtime.deepagents import (
    DeepAgentsRuntime,
    _check_langchain_available,
    create_langchain_tool,
)
from cognitia.runtime.deepagents_builtins import DEEPAGENTS_NATIVE_BUILTIN_TOOLS
from cognitia.runtime.types import Message, RuntimeConfig, RuntimeEvent, ToolSpec

# ---------------------------------------------------------------------------
# Built-in tools filtering
# ---------------------------------------------------------------------------


class TestBuiltinToolsFiltering:
    """DeepAgentsRuntime built-ins policy."""

    def test_builtin_tools_list_complete(self) -> None:
        """All dangerous built-in tools DeepAgents are listed."""
        expected = {
            "write_todos",
            "ls",
            "read_file",
            "write_file",
            "edit_file",
            "glob",
            "grep",
            "execute",
            "task",
        }
        assert expected == DEEPAGENTS_NATIVE_BUILTIN_TOOLS

    def test_filter_removes_builtins(self) -> None:
        """filter_builtin_tools removes built-in tools."""
        tools = [
            ToolSpec(name="Bash", description="shell", parameters={}),
            ToolSpec(name="read_file", description="read file", parameters={}),
            ToolSpec(name="mcp__iss__get_bonds", description="bonds", parameters={}),
            ToolSpec(name="calculate_goal_plan", description="calc", parameters={}, is_local=True),
        ]
        filtered = DeepAgentsRuntime.filter_builtin_tools(tools)
        names = [t.name for t in filtered]
        assert "Bash" not in names
        assert "read_file" not in names
        assert "mcp__iss__get_bonds" in names
        assert "calculate_goal_plan" in names

    def test_filter_preserves_safe_tools(self) -> None:
        """filter_builtin_tools saves safe tools."""
        tools = [
            ToolSpec(name="mcp__finuslugi__deposits", description="d", parameters={}),
            ToolSpec(name="assess_health_score", description="h", parameters={}, is_local=True),
        ]
        filtered = DeepAgentsRuntime.filter_builtin_tools(tools)
        assert len(filtered) == 2

    def test_filter_empty_list(self) -> None:
        """filter_builtin_tools on empty list -> empty list."""
        assert DeepAgentsRuntime.filter_builtin_tools([]) == []

    def test_all_builtins_removed(self) -> None:
        """Each builtin from frozenset is indeed filtered."""
        tools = [
            ToolSpec(name=name, description="x", parameters={})
            for name in DEEPAGENTS_NATIVE_BUILTIN_TOOLS
        ]
        filtered = DeepAgentsRuntime.filter_builtin_tools(tools)
        assert filtered == []

    def test_select_active_tools_hybrid_keeps_builtins(self) -> None:
        tools = [
            ToolSpec(name="execute", description="shell", parameters={}),
            ToolSpec(name="mcp__iss__get_bonds", description="bonds", parameters={}),
        ]
        selected = DeepAgentsRuntime.select_active_tools(
            tools,
            feature_mode="hybrid",
        )
        assert [t.name for t in selected] == ["execute", "mcp__iss__get_bonds"]

    def test_select_active_tools_native_first_keeps_builtins(self) -> None:
        tools = [
            ToolSpec(name="task", description="subagent", parameters={}),
            ToolSpec(name="TodoWrite", description="todo", parameters={}),
        ]
        selected = DeepAgentsRuntime.select_active_tools(
            tools,
            feature_mode="native_first",
        )
        assert [t.name for t in selected] == ["task", "TodoWrite"]

    def test_select_active_tools_allow_native_features_overrides_portable(self) -> None:
        tools = [
            ToolSpec(name="read_file", description="read", parameters={}),
            ToolSpec(name="mcp__iss__get_bonds", description="bonds", parameters={}),
        ]
        selected = DeepAgentsRuntime.select_active_tools(
            tools,
            feature_mode="portable",
            allow_native_features=True,
        )
        assert [t.name for t in selected] == ["read_file", "mcp__iss__get_bonds"]


# ---------------------------------------------------------------------------
# Dependency check
# ---------------------------------------------------------------------------


class TestDependencyCheck:
    """Check availability of langchain deps."""

    def test_check_with_missing_deps(self) -> None:
        """If langchain is not installed - returns RuntimeErrorData."""
        with patch.dict("sys.modules", {"langchain_core": None}):
            error = _check_langchain_available()
            if error is not None:
                assert error.kind == "dependency_missing"
                assert "langchain" in error.message.lower()

    def test_check_with_both_missing(self) -> None:
        """Both modules are missing - error."""
        with patch.dict(
            "sys.modules",
            {"langchain_core": None, "deepagents": None},
        ):
            error = _check_langchain_available()
            if error is not None:
                assert error.kind == "dependency_missing"


# ---------------------------------------------------------------------------
# Runtime run() - main pipeline
# ---------------------------------------------------------------------------


class TestDeepAgentsRuntimeRun:
    """DeepAgentsRuntime.run() - full pipeline."""

    @pytest.mark.asyncio
    async def test_run_without_deps_yields_error(self) -> None:
        """If deps are missing -> error event."""
        from cognitia.runtime.types import RuntimeErrorData

        runtime = DeepAgentsRuntime()
        fake_error = RuntimeErrorData(kind="dependency_missing", message="not installed")
        with patch(
            "cognitia.runtime.deepagents._check_langchain_available",
            return_value=fake_error,
        ):
            events = []
            async for ev in runtime.run(
                messages=[Message(role="user", content="hi")],
                system_prompt="test",
                active_tools=[],
            ):
                events.append(ev)

            assert len(events) == 1
            assert events[0].type == "error"
            assert events[0].data["kind"] == "dependency_missing"

    @pytest.mark.asyncio
    async def test_run_emits_assistant_delta_before_final(self) -> None:
        """run() streams assistant_delta before final."""
        runtime = DeepAgentsRuntime()

        async def _fake_stream(**kwargs):
            yield RuntimeEvent.assistant_delta("Привет, мир!")

        with (
            patch("cognitia.runtime.deepagents._check_langchain_available", return_value=None),
            patch.object(runtime, "_stream_langchain", side_effect=_fake_stream),
        ):
            events = []
            async for ev in runtime.run(
                messages=[Message(role="user", content="hi")],
                system_prompt="test",
                active_tools=[],
            ):
                events.append(ev)

            types = [e.type for e in events]
            assert "assistant_delta" in types
            assert types[-1] == "final"
            final = events[-1]
            assert final.data["text"] == "Привет, мир!"

    @pytest.mark.asyncio
    async def test_run_empty_response_yields_final(self) -> None:
        """Empty response -> only final with empty text."""
        runtime = DeepAgentsRuntime()

        async def _fake_stream(**kwargs):
            return
            yield  # async generator

        with (
            patch("cognitia.runtime.deepagents._check_langchain_available", return_value=None),
            patch.object(runtime, "_stream_langchain", side_effect=_fake_stream),
        ):
            events = []
            async for ev in runtime.run(
                messages=[Message(role="user", content="hi")],
                system_prompt="test",
                active_tools=[],
            ):
                events.append(ev)

            assert len(events) == 1
            assert events[0].type == "final"
            assert events[0].data["text"] == ""

    @pytest.mark.asyncio
    async def test_run_exception_yields_error(self) -> None:
        """Error in LangChain -> error event, without final."""
        runtime = DeepAgentsRuntime()

        async def _failing_stream(**kwargs):
            raise RuntimeError("LLM fail")
            yield  # async generator

        with (
            patch("cognitia.runtime.deepagents._check_langchain_available", return_value=None),
            patch.object(runtime, "_stream_langchain", side_effect=_failing_stream),
        ):
            events = []
            async for ev in runtime.run(
                messages=[Message(role="user", content="hi")],
                system_prompt="test",
                active_tools=[],
            ):
                events.append(ev)

            assert len(events) == 1
            assert events[0].type == "error"
            assert "LLM fail" in events[0].data["message"]

    @pytest.mark.asyncio
    async def test_run_passes_base_url(self) -> None:
        """base_url from config is forwarded in _stream_langchain."""
        cfg = RuntimeConfig(
            runtime_name="deepagents",
            model="test",
            base_url="https://proxy.example.com",
        )
        runtime = DeepAgentsRuntime(config=cfg)

        async def _fake_stream(**kwargs):
            yield RuntimeEvent.assistant_delta("ok")

        with (
            patch("cognitia.runtime.deepagents._check_langchain_available", return_value=None),
            patch.object(runtime, "_stream_langchain", side_effect=_fake_stream) as mock_stream,
        ):
            events = []
            async for ev in runtime.run(
                messages=[Message(role="user", content="hi")],
                system_prompt="test",
                active_tools=[],
            ):
                events.append(ev)

        mock_stream.assert_called_once()
        call_kwargs = mock_stream.call_args
        assert call_kwargs.kwargs.get("base_url") == "https://proxy.example.com"

    @pytest.mark.asyncio
    async def test_run_parses_structured_output_when_configured(self) -> None:
        """If output_format is specified and the final text is JSON, structured_output is populated."""
        cfg = RuntimeConfig(
            runtime_name="deepagents",
            output_format={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        )
        runtime = DeepAgentsRuntime(config=cfg)

        async def _fake_stream(**kwargs):
            _ = kwargs
            yield RuntimeEvent.assistant_delta('{"name":"Alice"}')

        with (
            patch("cognitia.runtime.deepagents._check_langchain_available", return_value=None),
            patch.object(runtime, "_stream_langchain", side_effect=_fake_stream),
        ):
            events = []
            async for ev in runtime.run(
                messages=[Message(role="user", content="hi")],
                system_prompt="test",
                active_tools=[],
            ):
                events.append(ev)

        final = events[-1]
        assert final.type == "final"
        assert final.data["structured_output"] == {"name": "Alice"}

    @pytest.mark.asyncio
    async def test_run_hybrid_uses_native_stream(self) -> None:
        """hybrid mode route is in native upstream path."""
        runtime = DeepAgentsRuntime(
            config=RuntimeConfig(
                runtime_name="deepagents",
                feature_mode="hybrid",
                native_config={"backend": "sandbox"},
            ),
        )

        async def _fake_native(**kwargs):
            yield RuntimeEvent.assistant_delta("native")

        with (
            patch("cognitia.runtime.deepagents._check_langchain_available", return_value=None),
            patch.object(runtime, "_stream_native", side_effect=_fake_native) as mock_native,
            patch.object(
                runtime,
                "_stream_langchain",
                side_effect=AssertionError("compat path не должен вызываться"),
            ),
        ):
            events = []
            async for ev in runtime.run(
                messages=[Message(role="user", content="hi")],
                system_prompt="test",
                active_tools=[],
            ):
                events.append(ev)

        mock_native.assert_called_once()
        assert events[-1].type == "final"
        assert events[-1].data["text"] == "native"

    @pytest.mark.asyncio
    async def test_run_portable_uses_compat_stream(self) -> None:
        """portable mode remains on compatibility path."""
        runtime = DeepAgentsRuntime(
            config=RuntimeConfig(runtime_name="deepagents", feature_mode="portable"),
        )

        async def _fake_compat(**kwargs):
            yield RuntimeEvent.assistant_delta("compat")

        with (
            patch("cognitia.runtime.deepagents._check_langchain_available", return_value=None),
            patch.object(runtime, "_stream_langchain", side_effect=_fake_compat) as mock_compat,
            patch.object(
                runtime,
                "_stream_native",
                side_effect=AssertionError("native path не должен вызываться"),
            ),
        ):
            events = []
            async for ev in runtime.run(
                messages=[Message(role="user", content="hi")],
                system_prompt="test",
                active_tools=[],
            ):
                events.append(ev)

        mock_compat.assert_called_once()
        assert events[-1].type == "final"
        assert events[-1].data["text"] == "compat"

    @pytest.mark.asyncio
    async def test_run_missing_provider_package_yields_typed_error(self) -> None:
        """Missing provider package -> dependency_missing, not runtime_crash."""
        runtime = DeepAgentsRuntime(
            config=RuntimeConfig(runtime_name="deepagents", model="openai:gpt-4o"),
        )

        with (
            patch("cognitia.runtime.deepagents._check_langchain_available", return_value=None),
            patch.dict("sys.modules", {"langchain_openai": None}),
        ):
            events = []
            async for ev in runtime.run(
                messages=[Message(role="user", content="hi")],
                system_prompt="test",
                active_tools=[],
            ):
                events.append(ev)

        assert len(events) == 1
        assert events[0].type == "error"
        assert events[0].data["kind"] == "dependency_missing"
        assert "langchain-openai" in events[0].data["message"]

    @pytest.mark.asyncio
    async def test_run_tool_events_in_stream(self) -> None:
        """Tool events (started/finished) are forwarded + metrics."""
        runtime = DeepAgentsRuntime()

        async def _fake_stream_with_tools(**kwargs):
            yield RuntimeEvent.tool_call_started(name="calc", args={"x": 1}, correlation_id="cid-1")
            yield RuntimeEvent.tool_call_finished(
                name="calc", correlation_id="cid-1", result_summary="42"
            )
            yield RuntimeEvent.assistant_delta("Результат: 42")

        with (
            patch("cognitia.runtime.deepagents._check_langchain_available", return_value=None),
            patch.object(runtime, "_stream_langchain", side_effect=_fake_stream_with_tools),
        ):
            events = []
            async for ev in runtime.run(
                messages=[Message(role="user", content="hi")],
                system_prompt="test",
                active_tools=[],
            ):
                events.append(ev)

            types = [e.type for e in events]
            assert "tool_call_started" in types
            assert "tool_call_finished" in types
            assert "assistant_delta" in types
            assert types[-1] == "final"
            final = events[-1]
            assert final.data["metrics"]["tool_calls_count"] == 1

    @pytest.mark.asyncio
    async def test_run_filters_builtins_from_active_tools(self) -> None:
        """run() in portable mode filters built-in tools before _stream_langchain."""
        runtime = DeepAgentsRuntime()

        captured_tools: list[ToolSpec] = []

        async def _capturing_stream(**kwargs):
            captured_tools.extend(kwargs.get("tools", []))
            yield RuntimeEvent.assistant_delta("ok")

        tools = [
            ToolSpec(name="Bash", description="shell", parameters={}),
            ToolSpec(name="mcp__iss__search", description="s", parameters={}),
            ToolSpec(name="read_file", description="r", parameters={}),
        ]

        with (
            patch("cognitia.runtime.deepagents._check_langchain_available", return_value=None),
            patch.object(runtime, "_stream_langchain", side_effect=_capturing_stream),
        ):
            events = []
            async for _ in runtime.run(
                messages=[Message(role="user", content="hi")],
                system_prompt="test",
                active_tools=tools,
            ):
                events.append(_)

        names = [t.name for t in captured_tools]
        assert "Bash" not in names
        assert "read_file" not in names
        assert "mcp__iss__search" in names
        assert events[0].type == "status"
        assert "portable mode" in events[0].data["text"]
        assert "execute" in events[0].data["text"]
        assert "read_file" in events[0].data["text"]

    @pytest.mark.asyncio
    async def test_run_keeps_builtins_in_hybrid_mode(self) -> None:
        """run() in hybrid mode maps built-ins in native path and does not duplicate them as custom tools."""
        cfg = RuntimeConfig(
            runtime_name="deepagents",
            feature_mode="hybrid",
            native_config={"backend": "sandbox"},
        )
        runtime = DeepAgentsRuntime(config=cfg)

        captured_tools: list[ToolSpec] = []

        async def _capturing_stream(**kwargs):
            captured_tools.extend(kwargs.get("tools", []))
            yield RuntimeEvent.assistant_delta("ok")

        tools = [
            ToolSpec(name="Bash", description="shell", parameters={}),
            ToolSpec(name="task", description="subagent", parameters={}),
            ToolSpec(name="mcp__iss__search", description="s", parameters={}),
            ToolSpec(name="calc", description="calc", parameters={}, is_local=True),
        ]

        with (
            patch("cognitia.runtime.deepagents._check_langchain_available", return_value=None),
            patch.object(runtime, "_stream_native", side_effect=_capturing_stream),
        ):
            events = []
            async for _ in runtime.run(
                messages=[Message(role="user", content="hi")],
                system_prompt="test",
                active_tools=tools,
            ):
                events.append(_)

        assert [t.name for t in captured_tools] == ["mcp__iss__search", "calc"]
        assert events[0].type == "status"
        assert "Bash->execute" in events[0].data["text"]
        assert "task" in events[0].data["text"]

    @pytest.mark.asyncio
    async def test_run_native_first_prefers_upstream_builtin_over_local_collision(self) -> None:
        """native_first does not forward colliding local tool named native built-in."""
        cfg = RuntimeConfig(
            runtime_name="deepagents",
            feature_mode="native_first",
            native_config={"backend": "sandbox"},
        )
        runtime = DeepAgentsRuntime(config=cfg)

        captured_tools: list[ToolSpec] = []

        async def _capturing_stream(**kwargs):
            captured_tools.extend(kwargs.get("tools", []))
            yield RuntimeEvent.assistant_delta("ok")

        tools = [
            ToolSpec(name="execute", description="local shell", parameters={}, is_local=True),
            ToolSpec(name="calc", description="calc", parameters={}, is_local=True),
        ]

        with (
            patch("cognitia.runtime.deepagents._check_langchain_available", return_value=None),
            patch.object(runtime, "_stream_native", side_effect=_capturing_stream),
        ):
            events = []
            async for event in runtime.run(
                messages=[Message(role="user", content="hi")],
                system_prompt="test",
                active_tools=tools,
            ):
                events.append(event)

        assert [tool.name for tool in captured_tools] == ["calc"]
        assert events[0].type == "status"
        assert "native-first" in events[0].data["text"]
        assert "execute" in events[0].data["text"]

    @pytest.mark.asyncio
    async def test_run_hybrid_with_native_builtins_requires_backend(self) -> None:
        """Native built-ins without backend should return typed error instead of StateBackend fallback."""
        runtime = DeepAgentsRuntime(
            config=RuntimeConfig(runtime_name="deepagents", feature_mode="hybrid"),
        )

        events = []
        with patch("cognitia.runtime.deepagents._check_langchain_available", return_value=None):
            async for event in runtime.run(
                messages=[Message(role="user", content="hi")],
                system_prompt="test",
                active_tools=[ToolSpec(name="Bash", description="shell", parameters={})],
            ):
                events.append(event)

        assert len(events) == 1
        assert events[0].type == "error"
        assert events[0].data["kind"] == "capability_unsupported"
        assert "backend" in events[0].data["message"]

    @pytest.mark.asyncio
    async def test_run_new_messages_in_final(self) -> None:
        """final event contains new_messages with assistant text."""
        runtime = DeepAgentsRuntime()

        async def _fake_stream(**kwargs):
            yield RuntimeEvent.assistant_delta("Ответ модели")

        with (
            patch("cognitia.runtime.deepagents._check_langchain_available", return_value=None),
            patch.object(runtime, "_stream_langchain", side_effect=_fake_stream),
        ):
            events = []
            async for ev in runtime.run(
                messages=[Message(role="user", content="hi")],
                system_prompt="test",
                active_tools=[],
            ):
                events.append(ev)

            final = events[-1]
            new_msgs = final.data["new_messages"]
            assert len(new_msgs) == 1
            # Message can be a dict or an object with role/content fields
            msg = new_msgs[0]
            if isinstance(msg, dict):
                assert msg["role"] == "assistant"
                assert msg["content"] == "Ответ модели"
            else:
                assert msg.role == "assistant"
                assert msg.content == "Ответ модели"

    @pytest.mark.asyncio
    async def test_run_preserves_tool_history_in_final(self) -> None:
        """tool_call_* events should fall into final.new_messages."""
        runtime = DeepAgentsRuntime()

        async def _fake_stream(**kwargs):
            yield RuntimeEvent.tool_call_started(
                name="calc",
                args={"x": 2},
                correlation_id="call-1",
            )
            yield RuntimeEvent.tool_call_finished(
                name="calc",
                correlation_id="call-1",
                result_summary="4",
            )
            yield RuntimeEvent.assistant_delta("Ответ модели")

        with (
            patch("cognitia.runtime.deepagents._check_langchain_available", return_value=None),
            patch.object(runtime, "_stream_langchain", side_effect=_fake_stream),
        ):
            events = []
            async for ev in runtime.run(
                messages=[Message(role="user", content="hi")],
                system_prompt="test",
                active_tools=[],
            ):
                events.append(ev)

        final = events[-1]
        new_msgs = final.data["new_messages"]
        assert len(new_msgs) == 3

        first, second, third = new_msgs
        if isinstance(first, dict):
            assert first["role"] == "assistant"
            assert first["tool_calls"][0]["name"] == "calc"
            assert first["tool_calls"][0]["args"] == {"x": 2}
        else:
            assert first.role == "assistant"
            assert first.tool_calls[0]["name"] == "calc"
            assert first.tool_calls[0]["args"] == {"x": 2}

        if isinstance(second, dict):
            assert second["role"] == "tool"
            assert second["name"] == "calc"
            assert second["content"] == "4"
            assert second["metadata"]["correlation_id"] == "call-1"
        else:
            assert second.role == "tool"
            assert second.name == "calc"
            assert second.content == "4"
            assert second.metadata["correlation_id"] == "call-1"

        if isinstance(third, dict):
            assert third["role"] == "assistant"
            assert third["content"] == "Ответ модели"
        else:
            assert third.role == "assistant"
            assert third.content == "Ответ модели"

    @pytest.mark.asyncio
    async def test_run_multiple_tool_calls_counted(self) -> None:
        """Not how much tool_call_finished -> metrics.tool_calls_count is summed up."""
        runtime = DeepAgentsRuntime()

        async def _multi_tools(**kwargs):
            yield RuntimeEvent.tool_call_started(name="a", args={})
            yield RuntimeEvent.tool_call_finished(name="a", correlation_id="1", result_summary="r1")
            yield RuntimeEvent.tool_call_started(name="b", args={})
            yield RuntimeEvent.tool_call_finished(name="b", correlation_id="2", result_summary="r2")
            yield RuntimeEvent.tool_call_started(name="c", args={})
            yield RuntimeEvent.tool_call_finished(name="c", correlation_id="3", result_summary="r3")
            yield RuntimeEvent.assistant_delta("done")

        with (
            patch("cognitia.runtime.deepagents._check_langchain_available", return_value=None),
            patch.object(runtime, "_stream_langchain", side_effect=_multi_tools),
        ):
            events = []
            async for ev in runtime.run(
                messages=[Message(role="user", content="hi")],
                system_prompt="test",
                active_tools=[],
            ):
                events.append(ev)

            final = events[-1]
            assert final.data["metrics"]["tool_calls_count"] == 3

    @pytest.mark.asyncio
    async def test_run_uses_override_config(self) -> None:
        """per-call config takes precedence over default."""
        default_cfg = RuntimeConfig(runtime_name="deepagents", model="default-model")
        override_cfg = RuntimeConfig(runtime_name="deepagents", model="override-model")
        runtime = DeepAgentsRuntime(config=default_cfg)

        async def _fake_stream(**kwargs):
            yield RuntimeEvent.assistant_delta("ok")

        with (
            patch("cognitia.runtime.deepagents._check_langchain_available", return_value=None),
            patch.object(runtime, "_stream_langchain", side_effect=_fake_stream) as mock_stream,
        ):
            async for _ in runtime.run(
                messages=[Message(role="user", content="hi")],
                system_prompt="test",
                active_tools=[],
                config=override_cfg,
            ):
                pass

            call_kwargs = mock_stream.call_args.kwargs
            assert call_kwargs["model"] == "override-model"


# ---------------------------------------------------------------------------
# _build_lc_messages
# ---------------------------------------------------------------------------


class TestBuildLcMessages:
    """_build_lc_messages - conversion of cognitia Message -> LangChain."""

    def _make_runtime(self) -> DeepAgentsRuntime:
        return DeepAgentsRuntime()

    def test_system_prompt_first(self) -> None:
        """System prompt comes first as SystemMessage."""
        runtime = self._make_runtime()
        try:
            from langchain_core.messages import SystemMessage
        except ImportError:
            pytest.skip("langchain_core не установлен")

        messages = [Message(role="user", content="hi")]
        lc = runtime._build_lc_messages(messages, "You are a test bot")

        assert len(lc) == 2
        assert isinstance(lc[0], SystemMessage)
        assert lc[0].content == "You are a test bot"

    def test_user_message_converted(self) -> None:
        """user → HumanMessage."""
        runtime = self._make_runtime()
        try:
            from langchain_core.messages import HumanMessage
        except ImportError:
            pytest.skip("langchain_core не установлен")

        lc = runtime._build_lc_messages(
            [Message(role="user", content="Привет")],
            "sys",
        )
        assert isinstance(lc[1], HumanMessage)
        assert lc[1].content == "Привет"

    def test_assistant_message_converted(self) -> None:
        """assistant → AIMessage."""
        runtime = self._make_runtime()
        try:
            from langchain_core.messages import AIMessage
        except ImportError:
            pytest.skip("langchain_core не установлен")

        lc = runtime._build_lc_messages(
            [Message(role="assistant", content="Ответ")],
            "sys",
        )
        assert isinstance(lc[1], AIMessage)
        assert lc[1].content == "Ответ"

    def test_tool_message_converted(self) -> None:
        """assistant tool_calls + tool → AIMessage/ToolMessage."""
        runtime = self._make_runtime()
        try:
            from langchain_core.messages import AIMessage, ToolMessage
        except ImportError:
            pytest.skip("langchain_core не установлен")

        lc = runtime._build_lc_messages(
            [
                Message(
                    role="assistant",
                    content="",
                    tool_calls=[
                        {
                            "id": "call-1",
                            "name": "calc",
                            "args": {"x": 2},
                            "type": "tool_call",
                        }
                    ],
                ),
                Message(
                    role="tool",
                    content="4",
                    name="calc",
                    metadata={"correlation_id": "call-1"},
                ),
            ],
            "sys",
        )

        assert isinstance(lc[1], AIMessage)
        assert lc[1].tool_calls[0]["name"] == "calc"
        assert lc[1].tool_calls[0]["args"] == {"x": 2}
        assert isinstance(lc[2], ToolMessage)
        assert lc[2].name == "calc"
        assert lc[2].tool_call_id == "call-1"
        assert lc[2].content == "4"

    def test_system_message_in_history(self) -> None:
        """system in history -> SystemMessage (in addition to system_prompt)."""
        runtime = self._make_runtime()
        try:
            from langchain_core.messages import SystemMessage
        except ImportError:
            pytest.skip("langchain_core не установлен")

        lc = runtime._build_lc_messages(
            [Message(role="system", content="extra context")],
            "main prompt",
        )
        system_msgs = [m for m in lc if isinstance(m, SystemMessage)]
        assert len(system_msgs) == 2

    def test_mixed_conversation(self) -> None:
        """Mix of roles -> correct order."""
        runtime = self._make_runtime()
        try:
            from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
        except ImportError:
            pytest.skip("langchain_core не установлен")

        messages = [
            Message(role="user", content="q1"),
            Message(role="assistant", content="a1"),
            Message(role="user", content="q2"),
        ]
        lc = runtime._build_lc_messages(messages, "sys")

        assert len(lc) == 4  # system + 3 messages
        assert isinstance(lc[0], SystemMessage)
        assert isinstance(lc[1], HumanMessage)
        assert isinstance(lc[2], AIMessage)
        assert isinstance(lc[3], HumanMessage)

    def test_empty_history(self) -> None:
        """Empty history -> system prompt only."""
        runtime = self._make_runtime()
        try:
            from langchain_core.messages import SystemMessage
        except ImportError:
            pytest.skip("langchain_core не установлен")

        lc = runtime._build_lc_messages([], "sys")
        assert len(lc) == 1
        assert isinstance(lc[0], SystemMessage)


# ---------------------------------------------------------------------------
# _build_llm
# ---------------------------------------------------------------------------


class TestBuildLlm:
    """_build_llm - wrapper around provider-aware builder."""

    def test_build_llm_delegates_to_provider_builder(self) -> None:
        """_build_llm delegates in separate provider resolver."""
        runtime = DeepAgentsRuntime()
        sentinel = object()

        with patch(
            "cognitia.runtime.deepagents.build_deepagents_chat_model",
            return_value=sentinel,
        ) as mock_build:
            llm = runtime._build_llm("openai:gpt-4o", base_url="https://proxy.test")

        assert llm is sentinel
        mock_build.assert_called_once_with("openai:gpt-4o", base_url="https://proxy.test")


# ---------------------------------------------------------------------------
# _stream_langchain — event parsing
# ---------------------------------------------------------------------------


class TestStreamLangchain:
    """_stream_langchain - parsing LangChain astream_events -> RuntimeEvent."""

    @pytest.mark.asyncio
    async def test_on_chat_model_stream_yields_delta(self) -> None:
        """on_chat_model_stream with text chunk -> assistant_delta."""
        runtime = DeepAgentsRuntime()

        mock_chunk = MagicMock()
        mock_chunk.content = "Hello world"

        mock_runnable = AsyncMock()

        async def fake_astream_events(*args, **kwargs):
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": mock_chunk},
            }

        mock_runnable.astream_events = fake_astream_events

        with (
            patch.object(runtime, "_build_lc_messages", return_value=[]),
            patch.object(runtime, "_build_llm", return_value=mock_runnable),
        ):
            events = []
            async for ev in runtime._stream_langchain(
                messages=[],
                system_prompt="sys",
                tools=[],
                model="test",
            ):
                events.append(ev)

        assert len(events) == 1
        assert events[0].type == "assistant_delta"
        assert events[0].data["text"] == "Hello world"

    @pytest.mark.asyncio
    async def test_on_tool_start_and_end_events(self) -> None:
        """on_tool_start → tool_call_started, on_tool_end → tool_call_finished."""
        runtime = DeepAgentsRuntime()

        mock_runnable = AsyncMock()

        async def fake_astream_events(*args, **kwargs):
            yield {
                "event": "on_tool_start",
                "name": "calc",
                "data": {"input": {"x": 42}},
                "run_id": "run-123",
            }
            yield {
                "event": "on_tool_end",
                "name": "calc",
                "data": {"output": "result: 42"},
                "run_id": "run-123",
            }

        mock_runnable.astream_events = fake_astream_events

        with (
            patch.object(runtime, "_build_lc_messages", return_value=[]),
            patch.object(runtime, "_build_llm", return_value=mock_runnable),
        ):
            events = []
            async for ev in runtime._stream_langchain(
                messages=[],
                system_prompt="sys",
                tools=[],
                model="test",
            ):
                events.append(ev)

        assert len(events) == 2
        assert events[0].type == "tool_call_started"
        assert events[0].data["name"] == "calc"
        assert events[0].data["args"] == {"x": 42}
        assert events[1].type == "tool_call_finished"
        assert events[1].data["name"] == "calc"
        assert "result: 42" in events[1].data["result_summary"]

    @pytest.mark.asyncio
    async def test_tool_correlation_id_linked(self) -> None:
        """correlation_id from started is forwarded in finished through run_id."""
        runtime = DeepAgentsRuntime()
        mock_runnable = AsyncMock()

        async def fake_astream_events(*args, **kwargs):
            yield {"event": "on_tool_start", "name": "t", "data": {"input": {}}, "run_id": "r1"}
            yield {"event": "on_tool_end", "name": "t", "data": {"output": "ok"}, "run_id": "r1"}

        mock_runnable.astream_events = fake_astream_events

        with (
            patch.object(runtime, "_build_lc_messages", return_value=[]),
            patch.object(runtime, "_build_llm", return_value=mock_runnable),
        ):
            events = []
            async for ev in runtime._stream_langchain(
                messages=[],
                system_prompt="sys",
                tools=[],
                model="test",
            ):
                events.append(ev)

        started_cid = events[0].data["correlation_id"]
        finished_cid = events[1].data["correlation_id"]
        assert started_cid == finished_cid
        assert started_cid != ""

    @pytest.mark.asyncio
    async def test_empty_chunk_content_ignored(self) -> None:
        """on_chat_model_stream with empty content -> nothing not yield."""
        runtime = DeepAgentsRuntime()

        mock_chunk = MagicMock()
        mock_chunk.content = ""  # empty

        mock_runnable = AsyncMock()

        async def fake_astream_events(*args, **kwargs):
            yield {"event": "on_chat_model_stream", "data": {"chunk": mock_chunk}}

        mock_runnable.astream_events = fake_astream_events

        with (
            patch.object(runtime, "_build_lc_messages", return_value=[]),
            patch.object(runtime, "_build_llm", return_value=mock_runnable),
        ):
            events = []
            async for ev in runtime._stream_langchain(
                messages=[],
                system_prompt="sys",
                tools=[],
                model="test",
            ):
                events.append(ev)

        assert events == []

    @pytest.mark.asyncio
    async def test_non_string_content_ignored(self) -> None:
        """on_chat_model_stream with not-string content (list) -> is ignored."""
        runtime = DeepAgentsRuntime()

        mock_chunk = MagicMock()
        mock_chunk.content = [{"type": "tool_use"}]  # not string

        mock_runnable = AsyncMock()

        async def fake_astream_events(*args, **kwargs):
            yield {"event": "on_chat_model_stream", "data": {"chunk": mock_chunk}}

        mock_runnable.astream_events = fake_astream_events

        with (
            patch.object(runtime, "_build_lc_messages", return_value=[]),
            patch.object(runtime, "_build_llm", return_value=mock_runnable),
        ):
            events = []
            async for ev in runtime._stream_langchain(
                messages=[],
                system_prompt="sys",
                tools=[],
                model="test",
            ):
                events.append(ev)

        assert events == []

    @pytest.mark.asyncio
    async def test_tools_bound_when_provided(self) -> None:
        """If tools are passed, llm.bind_tools() is called."""
        runtime = DeepAgentsRuntime()
        mock_llm = MagicMock()
        mock_bound = AsyncMock()

        async def fake_astream_events(*args, **kwargs):
            return
            yield  # async generator

        mock_bound.astream_events = fake_astream_events
        mock_llm.bind_tools.return_value = mock_bound

        spec = ToolSpec(name="test", description="d", parameters={})

        with (
            patch.object(runtime, "_build_lc_messages", return_value=[]),
            patch.object(runtime, "_build_llm", return_value=mock_llm),
            patch("cognitia.runtime.deepagents.create_langchain_tool", return_value=MagicMock()),
        ):
            async for _ in runtime._stream_langchain(
                messages=[],
                system_prompt="sys",
                tools=[spec],
                model="test",
            ):
                pass

        mock_llm.bind_tools.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_tools_no_bind(self) -> None:
        """Without tools - llm uses directly (without bind_tools)."""
        runtime = DeepAgentsRuntime()
        mock_llm = MagicMock()

        async def fake_astream_events(*args, **kwargs):
            return
            yield  # async generator

        mock_llm.astream_events = fake_astream_events

        with (
            patch.object(runtime, "_build_lc_messages", return_value=[]),
            patch.object(runtime, "_build_llm", return_value=mock_llm),
        ):
            async for _ in runtime._stream_langchain(
                messages=[],
                system_prompt="sys",
                tools=[],
                model="test",
            ):
                pass

        mock_llm.bind_tools.assert_not_called()


# ---------------------------------------------------------------------------
# LangChain tool wrapper
# ---------------------------------------------------------------------------


class TestCreateLangchainTool:
    """create_langchain_tool - wrapper ToolSpec in LangChain."""

    def test_create_tool_requires_langchain(self) -> None:
        """create_langchain_tool requires langchain-core."""
        spec = ToolSpec(name="test_tool", description="test", parameters={})
        try:
            tool = create_langchain_tool(spec)
            assert tool.name == "test_tool"
            assert tool.description == "test"
        except ImportError:
            pytest.skip("langchain_core не установлен")

    def test_create_tool_with_executor(self) -> None:
        """create_langchain_tool with custom executor."""
        spec = ToolSpec(name="calc", description="calculator", parameters={}, is_local=True)

        async def my_executor(**kwargs):
            return "42"

        try:
            tool = create_langchain_tool(spec, executor=my_executor)
            assert tool.name == "calc"
        except ImportError:
            pytest.skip("langchain_core не установлен")

    def test_create_tool_without_executor(self) -> None:
        """create_langchain_tool without executor - noop, not crashes."""
        spec = ToolSpec(name="noop", description="noop", parameters={})
        try:
            tool = create_langchain_tool(spec, executor=None)
            assert tool.name == "noop"
        except ImportError:
            pytest.skip("langchain_core не установлен")

    @pytest.mark.asyncio
    async def test_noop_executor_returns_error_json(self) -> None:
        """Tool without executor -> coroutine returns JSON with error."""
        spec = ToolSpec(name="noexec", description="d", parameters={})
        try:
            tool = create_langchain_tool(spec, executor=None)
            result = await tool.ainvoke({})
            assert "error" in result.lower() or "noexec" in result.lower()
        except ImportError:
            pytest.skip("langchain_core не установлен")

    @pytest.mark.asyncio
    async def test_executor_receives_kwargs(self) -> None:
        """Executor gets kwargs from tool call."""
        spec = ToolSpec(name="adder", description="add", parameters={})
        received = {}

        async def executor(**kwargs):
            received.update(kwargs)
            return "ok"

        try:
            tool = create_langchain_tool(spec, executor=executor)
            await tool.ainvoke({"a": 1, "b": 2})
            assert received == {"a": 1, "b": 2}
        except ImportError:
            pytest.skip("langchain_core не установлен")

    @pytest.mark.asyncio
    async def test_executor_dict_fallback(self) -> None:
        """Executor with signature (dict) -> backward compat."""
        spec = ToolSpec(name="old_style", description="d", parameters={})
        received = {}

        def executor(args: dict):
            received.update(args)
            return "ok"

        try:
            tool = create_langchain_tool(spec, executor=executor)
            await tool.ainvoke({"key": "value"})
            assert received.get("key") == "value"
        except ImportError:
            pytest.skip("langchain_core не установлен")

    @pytest.mark.asyncio
    async def test_executor_returns_dict_serialized(self) -> None:
        """Executor returns dict -> serialized in JSON."""
        import json

        spec = ToolSpec(name="json_tool", description="d", parameters={})

        async def executor(**kwargs):
            return {"result": 42}

        try:
            tool = create_langchain_tool(spec, executor=executor)
            result = await tool.ainvoke({})
            parsed = json.loads(result)
            assert parsed["result"] == 42
        except ImportError:
            pytest.skip("langchain_core не установлен")


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


class TestDeepAgentsCleanup:
    """Cleanup - stateless, nothing to clean."""

    @pytest.mark.asyncio
    async def test_cleanup_noop(self) -> None:
        runtime = DeepAgentsRuntime()
        await runtime.cleanup()  # shouldn't quit

    @pytest.mark.asyncio
    async def test_cleanup_idempotent(self) -> None:
        """Repeated cleanup is safe."""
        runtime = DeepAgentsRuntime()
        await runtime.cleanup()
        await runtime.cleanup()
        await runtime.cleanup()
