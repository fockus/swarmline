"""Тесты для hooks SDK bridge — конвертация HookRegistry → SDK HookMatcher."""

import pytest

pytest.importorskip("claude_agent_sdk", reason="claude-agent-sdk не установлен")

pytestmark = pytest.mark.requires_claude_sdk

from cognitia.hooks.registry import HookRegistry
from cognitia.hooks.sdk_bridge import registry_to_sdk_hooks


class TestRegistryToSdkHooks:
    """Конвертация HookRegistry → dict[HookEvent, list[HookMatcher]]."""

    def test_empty_registry_returns_none(self) -> None:
        """Пустой registry → None (не передавать hooks в SDK)."""
        registry = HookRegistry()
        result = registry_to_sdk_hooks(registry)
        assert result is None

    def test_pre_tool_use_hook_converted(self) -> None:
        """PreToolUse хук конвертируется в SDK формат."""
        registry = HookRegistry()

        async def my_hook(**kwargs):
            pass

        registry.on_pre_tool_use(my_hook, matcher="Bash")
        result = registry_to_sdk_hooks(registry)

        assert result is not None
        assert "PreToolUse" in result
        matchers = result["PreToolUse"]
        assert len(matchers) == 1
        assert matchers[0].matcher == "Bash"
        assert len(matchers[0].hooks) == 1

    def test_post_tool_use_hook_converted(self) -> None:
        """PostToolUse хук конвертируется в SDK формат."""
        registry = HookRegistry()

        async def my_hook(**kwargs):
            pass

        registry.on_post_tool_use(my_hook)
        result = registry_to_sdk_hooks(registry)

        assert result is not None
        assert "PostToolUse" in result

    def test_stop_hook_converted(self) -> None:
        """Stop хук конвертируется."""
        registry = HookRegistry()

        async def my_hook(**kwargs):
            pass

        registry.on_stop(my_hook)
        result = registry_to_sdk_hooks(registry)

        assert result is not None
        assert "Stop" in result
        assert result["Stop"][0].matcher is None

    def test_user_prompt_hook_converted(self) -> None:
        """UserPromptSubmit хук конвертируется."""
        registry = HookRegistry()

        async def my_hook(**kwargs):
            pass

        registry.on_user_prompt(my_hook)
        result = registry_to_sdk_hooks(registry)

        assert result is not None
        assert "UserPromptSubmit" in result

    def test_multiple_hooks_same_event(self) -> None:
        """Несколько хуков на одно событие → несколько HookMatcher."""
        registry = HookRegistry()

        async def hook_bash(**kwargs):
            pass

        async def hook_write(**kwargs):
            pass

        registry.on_pre_tool_use(hook_bash, matcher="Bash")
        registry.on_pre_tool_use(hook_write, matcher="Write")

        result = registry_to_sdk_hooks(registry)
        assert result is not None
        matchers = result["PreToolUse"]
        assert len(matchers) == 2

    def test_hooks_without_matcher_get_none_matcher(self) -> None:
        """Хук без matcher → HookMatcher.matcher = None."""
        registry = HookRegistry()

        async def my_hook(**kwargs):
            pass

        registry.on_pre_tool_use(my_hook)  # без matcher
        result = registry_to_sdk_hooks(registry)

        assert result is not None
        assert result["PreToolUse"][0].matcher is None

    @pytest.mark.asyncio
    async def test_sdk_callback_wraps_cognitia_callback(self) -> None:
        """SDK callback вызывает cognitia callback с правильными аргументами."""
        registry = HookRegistry()
        called_with = {}

        async def my_hook(**kwargs):
            called_with.update(kwargs)
            return {"continue_": True}

        registry.on_pre_tool_use(my_hook, matcher="Bash")
        result = registry_to_sdk_hooks(registry)

        # Вызываем SDK callback
        sdk_callback = result["PreToolUse"][0].hooks[0]
        hook_input = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
            "tool_use_id": "tu-123",
            "session_id": "sess-1",
            "transcript_path": "/tmp/t",
            "cwd": "/home",
        }
        output = await sdk_callback(hook_input, "tu-123", {"signal": None})

        assert "tool_name" in called_with
        assert called_with["tool_name"] == "Bash"
        assert output == {"continue_": True}

    @pytest.mark.asyncio
    async def test_sdk_callback_returns_default_on_none(self) -> None:
        """Если cognitia callback возвращает None → default output."""
        registry = HookRegistry()

        async def my_hook(**kwargs):
            return None

        registry.on_pre_tool_use(my_hook)
        result = registry_to_sdk_hooks(registry)

        sdk_callback = result["PreToolUse"][0].hooks[0]
        output = await sdk_callback(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "X",
                "tool_input": {},
                "tool_use_id": "t1",
                "session_id": "s",
                "transcript_path": "",
                "cwd": "",
            },
            "t1",
            {"signal": None},
        )
        assert output == {"continue_": True}
