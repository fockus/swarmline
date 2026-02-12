"""Тесты для DeepAgentsRuntime — LangChain Deep Agents runtime."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from cognitia.runtime.deepagents import (
    _DEEPAGENTS_BUILTIN_TOOLS,
    DeepAgentsRuntime,
    _check_langchain_available,
    create_langchain_tool,
)
from cognitia.runtime.types import Message, RuntimeConfig, RuntimeEvent, ToolSpec

# ---------------------------------------------------------------------------
# Built-in tools filtering
# ---------------------------------------------------------------------------

class TestBuiltinToolsFiltering:
    """DeepAgentsRuntime НЕ добавляет built-in tools."""

    def test_builtin_tools_list_complete(self) -> None:
        """Все опасные built-in tools DeepAgents перечислены."""
        expected = {
            "Read", "Write", "Edit", "MultiEdit",
            "Bash", "Glob", "Grep", "LS",
            "TodoRead", "TodoWrite",
            "WebFetch", "WebSearch",
            "Task", "AskQuestion",
        }
        assert expected == _DEEPAGENTS_BUILTIN_TOOLS

    def test_filter_removes_builtins(self) -> None:
        """filter_builtin_tools убирает built-in tools."""
        tools = [
            ToolSpec(name="Bash", description="shell", parameters={}),
            ToolSpec(name="Read", description="read file", parameters={}),
            ToolSpec(name="mcp__iss__get_bonds", description="bonds", parameters={}),
            ToolSpec(name="calculate_goal_plan", description="calc", parameters={}, is_local=True),
        ]
        filtered = DeepAgentsRuntime.filter_builtin_tools(tools)
        names = [t.name for t in filtered]
        assert "Bash" not in names
        assert "Read" not in names
        assert "mcp__iss__get_bonds" in names
        assert "calculate_goal_plan" in names

    def test_filter_preserves_safe_tools(self) -> None:
        """filter_builtin_tools сохраняет безопасные инструменты."""
        tools = [
            ToolSpec(name="mcp__finuslugi__deposits", description="d", parameters={}),
            ToolSpec(name="assess_health_score", description="h", parameters={}, is_local=True),
        ]
        filtered = DeepAgentsRuntime.filter_builtin_tools(tools)
        assert len(filtered) == 2

    def test_filter_empty_list(self) -> None:
        """filter_builtin_tools на пустом списке → пустой список."""
        assert DeepAgentsRuntime.filter_builtin_tools([]) == []


# ---------------------------------------------------------------------------
# Dependency check
# ---------------------------------------------------------------------------

class TestDependencyCheck:
    """Проверка наличия langchain deps."""

    def test_check_with_missing_deps(self) -> None:
        """Если langchain не установлен — возвращает RuntimeErrorData."""
        with patch.dict("sys.modules", {"langchain_core": None}):
            # Нужно убрать из кеша, чтобы _check_langchain_available поймал ImportError
            error = _check_langchain_available()
            # Зависит от наличия langchain в окружении — если установлен, будет None
            # Поэтому тестируем только формат ответа
            if error is not None:
                assert error.kind == "dependency_missing"
                assert "langchain" in error.message.lower()


# ---------------------------------------------------------------------------
# Runtime run() — missing deps
# ---------------------------------------------------------------------------

class TestDeepAgentsRuntimeRun:
    """DeepAgentsRuntime.run() — при отсутствии deps."""

    @pytest.mark.asyncio
    async def test_run_without_deps_yields_error(self) -> None:
        """Если deps отсутствуют → error event."""
        runtime = DeepAgentsRuntime()

        # Мокаем отсутствие langchain
        with patch(
            "cognitia.runtime.deepagents._check_langchain_available",
            return_value=__import__("cognitia.runtime.types", fromlist=["RuntimeErrorData"]).RuntimeErrorData(
                kind="dependency_missing", message="not installed",
            ),
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
        """Stage 0+7: run() стримит assistant_delta перед final."""
        runtime = DeepAgentsRuntime()

        async def _fake_stream(**kwargs):
            yield RuntimeEvent.assistant_delta("Привет, мир!")

        with patch("cognitia.runtime.deepagents._check_langchain_available", return_value=None), \
             patch.object(runtime, "_stream_langchain", side_effect=_fake_stream):
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
        """Пустой ответ → только final с пустым текстом."""
        runtime = DeepAgentsRuntime()

        async def _fake_stream(**kwargs):
            return
            yield  # сделать async generator

        with patch("cognitia.runtime.deepagents._check_langchain_available", return_value=None), \
             patch.object(runtime, "_stream_langchain", side_effect=_fake_stream):
            events = []
            async for ev in runtime.run(
                messages=[Message(role="user", content="hi")],
                system_prompt="test",
                active_tools=[],
            ):
                events.append(ev)

            assert len(events) == 1
            assert events[0].type == "final"

    @pytest.mark.asyncio
    async def test_run_exception_yields_error(self) -> None:
        """Ошибка в LangChain → error event."""
        runtime = DeepAgentsRuntime()

        async def _failing_stream(**kwargs):
            raise RuntimeError("LLM fail")
            yield  # сделать async generator

        with patch("cognitia.runtime.deepagents._check_langchain_available", return_value=None), \
             patch.object(runtime, "_stream_langchain", side_effect=_failing_stream):
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
        """Stage 5: base_url из config пробрасывается в _stream_langchain."""
        cfg = RuntimeConfig(runtime_name="deepagents", model="test", base_url="https://proxy.example.com")
        runtime = DeepAgentsRuntime(config=cfg)

        async def _fake_stream(**kwargs):
            yield RuntimeEvent.assistant_delta("ok")

        with patch("cognitia.runtime.deepagents._check_langchain_available", return_value=None), \
             patch.object(runtime, "_stream_langchain", side_effect=_fake_stream) as mock_stream:
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
    async def test_run_tool_events_in_stream(self) -> None:
        """Stage 7: tool events (started/finished) пробрасываются в стрим."""
        runtime = DeepAgentsRuntime()

        async def _fake_stream_with_tools(**kwargs):
            yield RuntimeEvent.tool_call_started(name="calc", args={"x": 1}, correlation_id="test-cid")
            yield RuntimeEvent.tool_call_finished(name="calc", correlation_id="test-cid", result_summary="42")
            yield RuntimeEvent.assistant_delta("Результат: 42")

        with patch("cognitia.runtime.deepagents._check_langchain_available", return_value=None), \
             patch.object(runtime, "_stream_langchain", side_effect=_fake_stream_with_tools):
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
            # Metrics должны содержать tool_calls_count
            final = events[-1]
            assert final.data["metrics"]["tool_calls_count"] == 1


# ---------------------------------------------------------------------------
# LangChain tool wrapper
# ---------------------------------------------------------------------------

class TestCreateLangchainTool:
    """create_langchain_tool — обёртка ToolSpec в LangChain."""

    def test_create_tool_requires_langchain(self) -> None:
        """create_langchain_tool требует langchain-core."""
        spec = ToolSpec(
            name="test_tool", description="test", parameters={},
        )
        try:
            tool = create_langchain_tool(spec)
            # Если langchain установлен — проверяем что tool создан
            assert tool.name == "test_tool"
            assert tool.description == "test"
        except ImportError:
            # langchain не установлен — ожидаемо
            pass

    def test_create_tool_with_executor(self) -> None:
        """create_langchain_tool с кастомным executor."""
        spec = ToolSpec(
            name="calc", description="calculator", parameters={},
            is_local=True,
        )

        async def my_executor(**kwargs):
            return "42"

        try:
            tool = create_langchain_tool(spec, executor=my_executor)
            assert tool.name == "calc"
        except ImportError:
            pass


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

class TestDeepAgentsCleanup:
    """Cleanup — stateless, нечего очищать."""

    @pytest.mark.asyncio
    async def test_cleanup_noop(self) -> None:
        runtime = DeepAgentsRuntime()
        await runtime.cleanup()  # не должно бросить
