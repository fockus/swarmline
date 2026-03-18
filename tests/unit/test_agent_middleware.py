"""Unit: Middleware ABC + CostTracker + SecurityGuard."""

from __future__ import annotations

import pytest
from cognitia.agent.config import AgentConfig
from cognitia.agent.middleware import (
    BudgetExceededError,
    CostTracker,
    Middleware,
    SecurityGuard,
)
from cognitia.agent.result import Result

# ---------------------------------------------------------------------------
# Middleware Protocol/ABC
# ---------------------------------------------------------------------------


class TestMiddlewareProtocol:
    """Middleware ABC — default passthrough."""

    @pytest.mark.asyncio
    async def test_default_before_query_passthrough(self) -> None:
        """The Basic class skips the prompt without changing."""

        class NoopMiddleware(Middleware):
            pass

        mw = NoopMiddleware()
        config = AgentConfig(system_prompt="test")
        result = await mw.before_query("hello", config)
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_default_after_result_passthrough(self) -> None:
        """The Basic class passes Result without modification."""

        class NoopMiddleware(Middleware):
            pass

        mw = NoopMiddleware()
        r = Result(text="answer")
        result = await mw.after_result(r)
        assert result is r

    def test_default_get_hooks_returns_none(self) -> None:
        class NoopMiddleware(Middleware):
            pass

        mw = NoopMiddleware()
        assert mw.get_hooks() is None


class TestMiddlewareChainOrder:
    """Middleware are called in order of registration."""

    @pytest.mark.asyncio
    async def test_before_query_chain_order(self) -> None:
        """Middleware is applied sequentially to prompt."""
        log: list[str] = []

        class MW1(Middleware):
            async def before_query(self, prompt: str, config: AgentConfig) -> str:
                log.append("mw1")
                return prompt + "+mw1"

        class MW2(Middleware):
            async def before_query(self, prompt: str, config: AgentConfig) -> str:
                log.append("mw2")
                return prompt + "+mw2"

        chain = (MW1(), MW2())
        config = AgentConfig(system_prompt="test")

        prompt = "start"
        for mw in chain:
            prompt = await mw.before_query(prompt, config)

        assert prompt == "start+mw1+mw2"
        assert log == ["mw1", "mw2"]

    @pytest.mark.asyncio
    async def test_after_result_chain_order(self) -> None:
        """after_result middleware is applied sequentially."""

        class AddTag(Middleware):
            def __init__(self, tag: str) -> None:
                self.tag = tag

            async def after_result(self, result: Result) -> Result:
                from dataclasses import replace

                return replace(result, text=result.text + self.tag)

        chain = (AddTag("[1]"), AddTag("[2]"))
        r = Result(text="base")
        for mw in chain:
            r = await mw.after_result(r)

        assert r.text == "base[1][2]"


# ---------------------------------------------------------------------------
# CostTracker
# ---------------------------------------------------------------------------


class TestCostTracker:
    """CostTracker - budget control."""

    @pytest.mark.asyncio
    async def test_accumulates_cost(self) -> None:
        tracker = CostTracker(budget_usd=10.0)
        r1 = Result(text="a", total_cost_usd=2.5)
        r2 = Result(text="b", total_cost_usd=1.5)

        await tracker.after_result(r1)
        await tracker.after_result(r2)

        assert tracker.total_cost_usd == pytest.approx(4.0)

    @pytest.mark.asyncio
    async def test_raises_on_budget_exceeded(self) -> None:
        tracker = CostTracker(budget_usd=1.0)
        r = Result(text="x", total_cost_usd=1.5)

        with pytest.raises(BudgetExceededError, match=r"1\.0"):
            await tracker.after_result(r)

    @pytest.mark.asyncio
    async def test_raises_on_cumulative_budget_exceeded(self) -> None:
        tracker = CostTracker(budget_usd=2.0)
        r1 = Result(text="a", total_cost_usd=1.5)
        r2 = Result(text="b", total_cost_usd=0.8)

        await tracker.after_result(r1)
        with pytest.raises(BudgetExceededError):
            await tracker.after_result(r2)

    def test_reset(self) -> None:
        tracker = CostTracker(budget_usd=10.0)
        tracker._total_cost = 5.0
        tracker.reset()
        assert tracker.total_cost_usd == 0.0

    def test_total_property(self) -> None:
        tracker = CostTracker(budget_usd=10.0)
        assert tracker.total_cost_usd == 0.0

    @pytest.mark.asyncio
    async def test_none_cost_ignored(self) -> None:
        """Result without cost (None) - does not break the tracker."""
        tracker = CostTracker(budget_usd=10.0)
        r = Result(text="no cost")
        result = await tracker.after_result(r)
        assert tracker.total_cost_usd == 0.0
        assert result.text == "no cost"


# ---------------------------------------------------------------------------
# SecurityGuard
# ---------------------------------------------------------------------------


class TestSecurityGuard:
    """SecurityGuard - blocking dangerous patterns."""

    def test_hooks_registered(self) -> None:
        """get_hooks() returns HookRegistry with PreToolUse."""
        guard = SecurityGuard(block_patterns=["rm -rf"])
        hooks = guard.get_hooks()
        assert hooks is not None
        events = hooks.list_events()
        assert "PreToolUse" in events

    @pytest.mark.asyncio
    async def test_blocks_dangerous_pattern(self) -> None:
        """Hook blocks rm -rf in tool input."""
        guard = SecurityGuard(block_patterns=["rm -rf"])
        hooks = guard.get_hooks()
        assert hooks is not None

        entries = hooks.get_hooks("PreToolUse")
        assert len(entries) == 1

        callback = entries[0].callback
        result = await callback(
            hook_event_name="PreToolUse",
            tool_name="Bash",
            tool_input={"command": "rm -rf /"},
        )
        assert result.get("decision") == "block"

    @pytest.mark.asyncio
    async def test_allows_safe_command(self) -> None:
        """Without dangerous commands pass."""
        guard = SecurityGuard(block_patterns=["rm -rf"])
        hooks = guard.get_hooks()
        assert hooks is not None

        entries = hooks.get_hooks("PreToolUse")
        callback = entries[0].callback
        result = await callback(
            hook_event_name="PreToolUse",
            tool_name="Bash",
            tool_input={"command": "ls -la"},
        )
        assert result.get("decision") != "block"

    @pytest.mark.asyncio
    async def test_multiple_patterns(self) -> None:
        """Not how many patterns - any match -> block."""
        guard = SecurityGuard(block_patterns=["rm -rf", "DROP TABLE", "chmod 777"])
        hooks = guard.get_hooks()
        assert hooks is not None

        callback = hooks.get_hooks("PreToolUse")[0].callback

        r1 = await callback(tool_input={"command": "DROP TABLE users"})
        assert r1.get("decision") == "block"

        r2 = await callback(tool_input={"command": "chmod 777 /"})
        assert r2.get("decision") == "block"

        r3 = await callback(tool_input={"command": "echo hello"})
        assert r3.get("decision") != "block"
