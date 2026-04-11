"""Tests for hooks SDK bridge - conversion HookRegistry -> SDK HookMatcher."""

import pytest

pytest.importorskip("claude_agent_sdk", reason="claude-agent-sdk не установлен")

pytestmark = pytest.mark.requires_claude_sdk

from swarmline.hooks.registry import HookRegistry  # noqa: E402
from swarmline.hooks.sdk_bridge import registry_to_sdk_hooks  # noqa: E402


class TestRegistryToSdkHooks:
    """Conversion HookRegistry -> dict[HookEvent, list[HookMatcher]]."""

    def test_empty_registry_returns_none(self) -> None:
        """Empty registry -> None (not peredavat hooks in SDK)."""
        registry = HookRegistry()
        result = registry_to_sdk_hooks(registry)
        assert result is None

    def test_pre_tool_use_hook_converted(self) -> None:
        """PreToolUse hook convertssya in SDK format."""
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
        """PostToolUse hook convertssya in SDK format."""
        registry = HookRegistry()

        async def my_hook(**kwargs):
            pass

        registry.on_post_tool_use(my_hook)
        result = registry_to_sdk_hooks(registry)

        assert result is not None
        assert "PostToolUse" in result

    def test_stop_hook_converted(self) -> None:
        """Stop hook convertssya."""
        registry = HookRegistry()

        async def my_hook(**kwargs):
            pass

        registry.on_stop(my_hook)
        result = registry_to_sdk_hooks(registry)

        assert result is not None
        assert "Stop" in result
        assert result["Stop"][0].matcher is None

    def test_user_prompt_hook_converted(self) -> None:
        """UserPromptSubmit hook convertssya."""
        registry = HookRegistry()

        async def my_hook(**kwargs):
            pass

        registry.on_user_prompt(my_hook)
        result = registry_to_sdk_hooks(registry)

        assert result is not None
        assert "UserPromptSubmit" in result

    def test_multiple_hooks_same_event(self) -> None:
        """Notskolko hookov on odno event -> notskolko HookMatcher."""
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
        """Hook without matcher -> HookMatcher.matcher = None."""
        registry = HookRegistry()

        async def my_hook(**kwargs):
            pass

        registry.on_pre_tool_use(my_hook)  # without matcher
        result = registry_to_sdk_hooks(registry)

        assert result is not None
        assert result["PreToolUse"][0].matcher is None

    @pytest.mark.asyncio
    async def test_sdk_callback_wraps_swarmline_callback(self) -> None:
        """SDK callback vyzyvaet swarmline callback with pravilnymi argumentami."""
        registry = HookRegistry()
        called_with = {}

        async def my_hook(**kwargs):
            called_with.update(kwargs)
            return {"continue_": True}

        registry.on_pre_tool_use(my_hook, matcher="Bash")
        result = registry_to_sdk_hooks(registry)

        # Vyzyvaem SDK callback
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
        """If swarmline callback returns None -> default output."""
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
