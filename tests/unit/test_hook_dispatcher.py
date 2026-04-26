"""Tests for HookDispatcher Protocol and DefaultHookDispatcher.

Contract tests (pass for ANY correct HookDispatcher implementation)
+ unit tests for DefaultHookDispatcher specifics.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from swarmline.hooks.dispatcher import DefaultHookDispatcher, HookDispatcher, HookResult
from swarmline.hooks.registry import HookRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _allow_hook(**kwargs: Any) -> HookResult:
    """Hook that allows everything."""
    return HookResult.allow()


async def _block_hook(**kwargs: Any) -> HookResult:
    """Hook that blocks with a message."""
    return HookResult.block("blocked by policy")


async def _modify_hook(**kwargs: Any) -> HookResult:
    """Hook that modifies input."""
    return HookResult.modify({"key": "modified"})


async def _post_hook_passthrough(**kwargs: Any) -> str | None:
    """Post-tool hook that returns None (no modification)."""
    return None


async def _post_hook_modify(**kwargs: Any) -> str | None:
    """Post-tool hook that modifies output."""
    return "modified output"


async def _stop_hook(**kwargs: Any) -> None:
    """Stop hook — no return."""
    pass


async def _prompt_transform(**kwargs: Any) -> str:
    """Prompt hook that uppercases the prompt."""
    return kwargs.get("prompt", "").upper()


async def _prompt_add_prefix(**kwargs: Any) -> str:
    """Prompt hook that adds a prefix."""
    return "PREFIX: " + kwargs.get("prompt", "")


async def _raising_hook(**kwargs: Any) -> HookResult:
    """Hook that raises an exception."""
    raise RuntimeError("hook exploded")


async def _raising_post_hook(**kwargs: Any) -> str | None:
    """Post-tool hook that raises."""
    raise ValueError("post hook failed")


async def _raising_stop_hook(**kwargs: Any) -> None:
    """Stop hook that raises."""
    raise TypeError("stop hook crashed")


async def _raising_prompt_hook(**kwargs: Any) -> str:
    """Prompt hook that raises."""
    raise RuntimeError("prompt hook crashed")


# ===========================================================================
# 1. HookResult dataclass tests
# ===========================================================================


class TestHookResult:
    """HookResult frozen dataclass with factory methods."""

    def test_allow_factory_returns_allow_action(self) -> None:
        result = HookResult.allow()
        assert result.action == "allow"
        assert result.modified_input is None
        assert result.message is None

    def test_block_factory_returns_block_action_with_message(self) -> None:
        result = HookResult.block("access denied")
        assert result.action == "block"
        assert result.message == "access denied"
        assert result.modified_input is None

    def test_modify_factory_returns_modify_action_with_input(self) -> None:
        new_input = {"arg1": "val1"}
        result = HookResult.modify(new_input)
        assert result.action == "modify"
        assert result.modified_input == {"arg1": "val1"}
        assert result.message is None

    def test_hook_result_is_frozen(self) -> None:
        result = HookResult.allow()
        with pytest.raises(AttributeError):
            result.action = "block"  # type: ignore[misc]


# ===========================================================================
# 2. HookDispatcher Protocol contract tests
# ===========================================================================


class TestHookDispatcherProtocol:
    """Contract: DefaultHookDispatcher satisfies HookDispatcher Protocol."""

    def test_default_dispatcher_is_hook_dispatcher(self) -> None:
        reg = HookRegistry()
        dispatcher = DefaultHookDispatcher(reg)
        assert isinstance(dispatcher, HookDispatcher)

    def test_protocol_has_exactly_four_methods(self) -> None:
        """ISP: HookDispatcher has exactly 4 public methods."""
        public_methods = [
            m
            for m in dir(HookDispatcher)
            if not m.startswith("_") and callable(getattr(HookDispatcher, m, None))
        ]
        assert len(public_methods) == 4


# ===========================================================================
# 3. dispatch_pre_tool tests
# ===========================================================================


class TestDispatchPreTool:
    """dispatch_pre_tool: iterate hooks, apply matcher, handle block/modify/allow."""

    async def test_no_hooks_returns_allow(self) -> None:
        reg = HookRegistry()
        dispatcher = DefaultHookDispatcher(reg)
        result = await dispatcher.dispatch_pre_tool("some_tool", {"a": 1})
        assert result.action == "allow"

    async def test_allow_hook_returns_allow(self) -> None:
        reg = HookRegistry()
        reg.on_pre_tool_use(_allow_hook)
        dispatcher = DefaultHookDispatcher(reg)
        result = await dispatcher.dispatch_pre_tool("any_tool", {})
        assert result.action == "allow"

    async def test_block_hook_returns_block(self) -> None:
        reg = HookRegistry()
        reg.on_pre_tool_use(_block_hook)
        dispatcher = DefaultHookDispatcher(reg)
        result = await dispatcher.dispatch_pre_tool("dangerous_tool", {})
        assert result.action == "block"
        assert result.message == "blocked by policy"

    async def test_modify_hook_returns_modified_input(self) -> None:
        reg = HookRegistry()
        reg.on_pre_tool_use(_modify_hook)
        dispatcher = DefaultHookDispatcher(reg)
        result = await dispatcher.dispatch_pre_tool("tool", {"key": "original"})
        assert result.action == "modify"
        assert result.modified_input == {"key": "modified"}

    async def test_matcher_filters_by_tool_name(self) -> None:
        """Hook with matcher='mcp__*' only fires for matching tool names."""
        reg = HookRegistry()
        reg.on_pre_tool_use(_block_hook, matcher="mcp__*")
        dispatcher = DefaultHookDispatcher(reg)

        result_match = await dispatcher.dispatch_pre_tool("mcp__server__tool", {})
        assert result_match.action == "block"

        result_no_match = await dispatcher.dispatch_pre_tool("local_tool", {})
        assert result_no_match.action == "allow"

    async def test_empty_matcher_matches_all(self) -> None:
        """Hook with empty matcher fires for all tools."""
        reg = HookRegistry()
        reg.on_pre_tool_use(_block_hook, matcher="")
        dispatcher = DefaultHookDispatcher(reg)
        result = await dispatcher.dispatch_pre_tool("anything", {})
        assert result.action == "block"

    async def test_block_stops_iteration(self) -> None:
        """First block result stops further hook evaluation."""
        call_order: list[str] = []

        async def first_hook(**kwargs: Any) -> HookResult:
            call_order.append("first")
            return HookResult.block("first blocks")

        async def second_hook(**kwargs: Any) -> HookResult:
            call_order.append("second")
            return HookResult.allow()

        reg = HookRegistry()
        reg.on_pre_tool_use(first_hook)
        reg.on_pre_tool_use(second_hook)
        dispatcher = DefaultHookDispatcher(reg)

        result = await dispatcher.dispatch_pre_tool("tool", {})
        assert result.action == "block"
        assert call_order == ["first"]

    async def test_multiple_modify_hooks_chain_input(self) -> None:
        """Multiple modify hooks chain: each receives already-modified input."""

        async def add_x(**kwargs: Any) -> HookResult:
            tool_input = kwargs["tool_input"]
            return HookResult.modify({**tool_input, "x": 1})

        async def add_y(**kwargs: Any) -> HookResult:
            tool_input = kwargs["tool_input"]
            return HookResult.modify({**tool_input, "y": 2})

        reg = HookRegistry()
        reg.on_pre_tool_use(add_x)
        reg.on_pre_tool_use(add_y)
        dispatcher = DefaultHookDispatcher(reg)

        result = await dispatcher.dispatch_pre_tool("tool", {"original": True})
        assert result.action == "modify"
        assert result.modified_input == {"original": True, "x": 1, "y": 2}

    async def test_exception_in_pre_hook_is_fail_open(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Fail-open: exception in pre-tool hook → log warning, allow."""
        reg = HookRegistry()
        reg.on_pre_tool_use(_raising_hook)
        dispatcher = DefaultHookDispatcher(reg)

        with caplog.at_level(logging.WARNING):
            result = await dispatcher.dispatch_pre_tool("tool", {})

        assert result.action == "allow"
        assert "hook exploded" in caplog.text


# ===========================================================================
# 4. dispatch_post_tool tests
# ===========================================================================


class TestDispatchPostTool:
    """dispatch_post_tool: iterate hooks, return modified output or None."""

    async def test_no_hooks_returns_none(self) -> None:
        reg = HookRegistry()
        dispatcher = DefaultHookDispatcher(reg)
        result = await dispatcher.dispatch_post_tool("tool", {}, "output")
        assert result is None

    async def test_passthrough_hook_returns_none(self) -> None:
        reg = HookRegistry()
        reg.on_post_tool_use(_post_hook_passthrough)
        dispatcher = DefaultHookDispatcher(reg)
        result = await dispatcher.dispatch_post_tool("tool", {}, "output")
        assert result is None

    async def test_modifying_hook_returns_new_output(self) -> None:
        reg = HookRegistry()
        reg.on_post_tool_use(_post_hook_modify)
        dispatcher = DefaultHookDispatcher(reg)
        result = await dispatcher.dispatch_post_tool("tool", {}, "original")
        assert result == "modified output"

    async def test_exception_in_post_hook_is_fail_open(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Fail-open: exception in post-tool hook → log warning, return None."""
        reg = HookRegistry()
        reg.on_post_tool_use(_raising_post_hook)
        dispatcher = DefaultHookDispatcher(reg)

        with caplog.at_level(logging.WARNING):
            result = await dispatcher.dispatch_post_tool("tool", {}, "output")

        assert result is None
        assert "post hook failed" in caplog.text

    async def test_matcher_filters_post_hooks(self) -> None:
        """Post-tool hooks with matcher only fire for matching tools."""
        reg = HookRegistry()
        reg.on_post_tool_use(_post_hook_modify, matcher="special_*")
        dispatcher = DefaultHookDispatcher(reg)

        matched = await dispatcher.dispatch_post_tool("special_tool", {}, "out")
        assert matched == "modified output"

        unmatched = await dispatcher.dispatch_post_tool("other_tool", {}, "out")
        assert unmatched is None


# ===========================================================================
# 4b. Legacy dict format tests (backward compat with SecurityGuard, etc.)
# ===========================================================================


class TestLegacyDictPreToolFormat:
    """DefaultHookDispatcher coerces legacy dict returns from existing middleware."""

    async def test_legacy_block_dict_is_coerced_to_hook_result(self) -> None:
        async def legacy_block(**kwargs: Any) -> dict[str, Any]:
            return {"decision": "block", "reason": "pattern found"}

        reg = HookRegistry()
        reg.on_pre_tool_use(legacy_block)
        dispatcher = DefaultHookDispatcher(reg)
        result = await dispatcher.dispatch_pre_tool("tool", {})
        assert result.action == "block"
        assert result.message == "pattern found"

    async def test_legacy_continue_dict_is_coerced_to_allow(self) -> None:
        async def legacy_continue(**kwargs: Any) -> dict[str, Any]:
            return {"continue_": True}

        reg = HookRegistry()
        reg.on_pre_tool_use(legacy_continue)
        dispatcher = DefaultHookDispatcher(reg)
        result = await dispatcher.dispatch_pre_tool("tool", {})
        assert result.action == "allow"


class TestLegacyDictPostToolFormat:
    """DefaultHookDispatcher coerces legacy dict returns from post-tool middleware."""

    async def test_legacy_tool_result_dict_returns_string(self) -> None:
        async def legacy_compress(**kwargs: Any) -> dict[str, Any]:
            return {"tool_result": "compressed output"}

        reg = HookRegistry()
        reg.on_post_tool_use(legacy_compress)
        dispatcher = DefaultHookDispatcher(reg)
        result = await dispatcher.dispatch_post_tool("tool", {}, "original")
        assert result == "compressed output"

    async def test_legacy_continue_dict_returns_none(self) -> None:
        async def legacy_passthrough(**kwargs: Any) -> dict[str, Any]:
            return {"continue_": True}

        reg = HookRegistry()
        reg.on_post_tool_use(legacy_passthrough)
        dispatcher = DefaultHookDispatcher(reg)
        result = await dispatcher.dispatch_post_tool("tool", {}, "original")
        assert result is None


# ===========================================================================
# 5. dispatch_stop tests
# ===========================================================================


class TestDispatchStop:
    """dispatch_stop: call all stop hooks, swallow exceptions."""

    async def test_no_hooks_completes_silently(self) -> None:
        reg = HookRegistry()
        dispatcher = DefaultHookDispatcher(reg)
        await dispatcher.dispatch_stop("result text")

    async def test_calls_all_stop_hooks(self) -> None:
        called: list[str] = []

        async def hook_a(**kwargs: Any) -> None:
            called.append("a")

        async def hook_b(**kwargs: Any) -> None:
            called.append("b")

        reg = HookRegistry()
        reg.on_stop(hook_a)
        reg.on_stop(hook_b)
        dispatcher = DefaultHookDispatcher(reg)

        await dispatcher.dispatch_stop("done")
        assert called == ["a", "b"]

    async def test_exception_in_stop_hook_is_fail_open(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Fail-open: exception in stop hook → log warning, continue."""
        called: list[str] = []

        async def good_hook(**kwargs: Any) -> None:
            called.append("good")

        reg = HookRegistry()
        reg.on_stop(_raising_stop_hook)
        reg.on_stop(good_hook)
        dispatcher = DefaultHookDispatcher(reg)

        with caplog.at_level(logging.WARNING):
            await dispatcher.dispatch_stop("done")

        assert "good" in called
        assert "stop hook crashed" in caplog.text


# ===========================================================================
# 6. dispatch_user_prompt tests
# ===========================================================================


class TestDispatchUserPrompt:
    """dispatch_user_prompt: chain prompt transformations."""

    async def test_no_hooks_returns_original_prompt(self) -> None:
        reg = HookRegistry()
        dispatcher = DefaultHookDispatcher(reg)
        result = await dispatcher.dispatch_user_prompt("hello")
        assert result == "hello"

    async def test_single_hook_transforms_prompt(self) -> None:
        reg = HookRegistry()
        reg.on_user_prompt(_prompt_transform)
        dispatcher = DefaultHookDispatcher(reg)
        result = await dispatcher.dispatch_user_prompt("hello")
        assert result == "HELLO"

    async def test_chained_hooks_apply_in_order(self) -> None:
        """Multiple prompt hooks chain: output of first = input of second."""
        reg = HookRegistry()
        reg.on_user_prompt(_prompt_transform)  # "hello" -> "HELLO"
        reg.on_user_prompt(_prompt_add_prefix)  # "HELLO" -> "PREFIX: HELLO"
        dispatcher = DefaultHookDispatcher(reg)
        result = await dispatcher.dispatch_user_prompt("hello")
        assert result == "PREFIX: HELLO"

    async def test_exception_in_prompt_hook_is_fail_open(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Fail-open: exception in prompt hook → log warning, return current prompt."""
        reg = HookRegistry()
        reg.on_user_prompt(_raising_prompt_hook)
        dispatcher = DefaultHookDispatcher(reg)

        with caplog.at_level(logging.WARNING):
            result = await dispatcher.dispatch_user_prompt("hello")

        assert result == "hello"
        assert "prompt hook crashed" in caplog.text
