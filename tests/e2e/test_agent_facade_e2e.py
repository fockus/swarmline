"""E2E: Agent Facade - full scenarios with mock SDK. Verifies end-to-end: ot @tool dekoratsii do Result,
vklyuchaya middleware chain, SecurityGuard, CostTracker.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from cognitia.agent import (
    Agent,
    AgentConfig,
    BudgetExceededError,
    Conversation,
    CostTracker,
    SecurityGuard,
    tool,
)
from conftest import FakeStreamEvent

# ---------------------------------------------------------------------------
# E2E: One-shot query
# ---------------------------------------------------------------------------


class TestE2EOneShot:
    """Full cycle: Agent → query → Result."""

    @pytest.mark.asyncio
    async def test_one_shot_query_full_cycle(self) -> None:
        """Agent.query() -> mock stream -> Result with metricmi."""
        agent = Agent(AgentConfig(system_prompt="Be concise"))

        async def fake_stream(prompt):
            yield FakeStreamEvent(type="text_delta", text="Answer is 42")
            yield FakeStreamEvent(
                type="done",
                text="Answer is 42",
                is_final=True,
                session_id="sess-e2e",
                total_cost_usd=0.02,
                usage={"input_tokens": 50, "output_tokens": 10},
            )

        with patch.object(agent, "_execute_stream", side_effect=fake_stream):
            result = await agent.query("What is the meaning of life?")

        assert result.ok is True
        assert result.text == "Answer is 42"
        assert result.session_id == "sess-e2e"
        assert result.total_cost_usd == 0.02
        assert result.usage == {"input_tokens": 50, "output_tokens": 10}


class TestE2EStreaming:
    """Full cycle: Agent → stream → events."""

    @pytest.mark.asyncio
    async def test_streaming_collects_all_events(self) -> None:
        agent = Agent(AgentConfig(system_prompt="test"))

        async def fake_stream(prompt):
            yield FakeStreamEvent(type="text_delta", text="Hello ")
            yield FakeStreamEvent(type="text_delta", text="World")
            yield FakeStreamEvent(type="done", text="Hello World", is_final=True)

        with patch.object(agent, "_execute_stream", side_effect=fake_stream):
            events = []
            async for event in agent.stream("Hi"):
                events.append(event)

        text_events = [e for e in events if e.type == "text_delta"]
        assert len(text_events) == 2
        assert text_events[0].text == "Hello "
        assert text_events[1].text == "World"


# ---------------------------------------------------------------------------
# E2E: Conversation 3 turns
# ---------------------------------------------------------------------------


class TestE2EConversation:
    """Multi-turn conversation."""

    @pytest.mark.asyncio
    async def test_conversation_3_turns_with_history(self) -> None:
        """3 turns → history tracks all messages."""
        agent = Agent(AgentConfig(system_prompt="test"))
        conv = Conversation(agent=agent)

        turn_count = 0

        async def fake_execute(prompt):
            nonlocal turn_count
            turn_count += 1
            yield FakeStreamEvent(type="text_delta", text=f"R{turn_count}")
            yield FakeStreamEvent(
                type="done",
                text=f"R{turn_count}",
                is_final=True,
                session_id=f"s-{turn_count}",
            )

        with patch.object(conv, "_execute", side_effect=fake_execute):
            r1 = await conv.say("Q1")
            r2 = await conv.say("Q2")
            r3 = await conv.say("Q3")

        assert r1.text == "R1"
        assert r2.text == "R2"
        assert r3.text == "R3"
        assert len(conv.history) == 6
        assert all(conv.history[i].role == "user" for i in range(0, 6, 2))
        assert all(conv.history[i].role == "assistant" for i in range(1, 6, 2))


# ---------------------------------------------------------------------------
# E2E: SecurityGuard blocks dangerous commands
# ---------------------------------------------------------------------------


class TestE2ESecurityGuard:
    """SecurityGuard blocks via hook in full pipeline."""

    @pytest.mark.asyncio
    async def test_security_guard_hook_blocks(self) -> None:
        """SecurityGuard register hook → callback blocks rm -rf."""
        guard = SecurityGuard(block_patterns=["rm -rf", "DROP TABLE"])

        # Verify hooks are properly registered
        hooks = guard.get_hooks()
        assert hooks is not None

        pre_tool_entries = hooks.get_hooks("PreToolUse")
        assert len(pre_tool_entries) == 1

        callback = pre_tool_entries[0].callback

        # Test: dangerous command blocked
        result = await callback(
            hook_event_name="PreToolUse",
            tool_name="Bash",
            tool_input={"command": "rm -rf / --no-preserve-root"},
        )
        assert result["decision"] == "block"
        assert "rm -rf" in result["reason"]

        # Test: safe command allowed
        result = await callback(
            hook_event_name="PreToolUse",
            tool_name="Bash",
            tool_input={"command": "ls -la /tmp"},
        )
        assert result.get("decision") != "block"

    @pytest.mark.asyncio
    async def test_security_guard_in_agent_config(self) -> None:
        """SecurityGuard in middleware -> Agent config validen."""
        guard = SecurityGuard(block_patterns=["rm -rf"])
        config = AgentConfig(
            system_prompt="test",
            middleware=(guard,),
        )
        agent = Agent(config)

        # Guard hooks accessible via conversation merge
        conv = agent.conversation()
        merged = conv._merge_hooks()
        assert merged is not None
        assert "PreToolUse" in merged.list_events()


# ---------------------------------------------------------------------------
# E2E: CostTracker budget enforcement
# ---------------------------------------------------------------------------


class TestE2ECostTracker:
    """CostTracker tracks cost and enforces budget."""

    @pytest.mark.asyncio
    async def test_cost_tracker_budget_exceeded(self) -> None:
        """CostTracker raises BudgetExceededError when budget is blown."""
        tracker = CostTracker(budget_usd=0.05)
        config = AgentConfig(
            system_prompt="test",
            middleware=(tracker,),
        )
        agent = Agent(config)

        async def expensive_stream(prompt):
            yield FakeStreamEvent(
                type="done",
                text="expensive answer",
                is_final=True,
                total_cost_usd=0.10,  # Exceeds 0.05 budget
            )

        with (
            patch.object(agent, "_execute_stream", side_effect=expensive_stream),
            pytest.raises(BudgetExceededError, match=r"0\.05"),
        ):
            await agent.query("expensive question")

    @pytest.mark.asyncio
    async def test_cost_tracker_cumulative_across_queries(self) -> None:
        """CostTracker accumulates across multiple queries."""
        tracker = CostTracker(budget_usd=0.10)
        config = AgentConfig(
            system_prompt="test",
            middleware=(tracker,),
        )
        agent = Agent(config)

        async def cheap_stream(prompt):
            yield FakeStreamEvent(
                type="done",
                text="ok",
                is_final=True,
                total_cost_usd=0.04,
            )

        with patch.object(agent, "_execute_stream", side_effect=cheap_stream):
            r1 = await agent.query("q1")
            assert r1.ok is True
            assert tracker.total_cost_usd == pytest.approx(0.04)

            await agent.query("q2")
            assert tracker.total_cost_usd == pytest.approx(0.08)

            # Third query exceeds budget
            with pytest.raises(BudgetExceededError):
                await agent.query("q3")


# ---------------------------------------------------------------------------
# E2E: Top-level imports
# ---------------------------------------------------------------------------


class TestE2EPublicAPI:
    """Public API imports work."""

    def test_import_from_cognitia(self) -> None:
        """from cognitia import Agent, AgentConfig, tool, Result, Conversation."""
        from cognitia import Agent, AgentConfig, Conversation, Result, tool

        assert Agent is not None
        assert AgentConfig is not None
        assert Conversation is not None
        assert Result is not None
        assert tool is not None

    def test_import_from_cognitia_agent(self) -> None:
        """from cognitia.agent import all facade types."""
        from cognitia.agent import (
            Agent,
            AgentConfig,
            BudgetExceededError,
            Conversation,
            CostTracker,
            Middleware,
            Result,
            SecurityGuard,
            ToolDefinition,
        )

        assert all(
            [
                Agent,
                AgentConfig,
                BudgetExceededError,
                Conversation,
                CostTracker,
                Middleware,
                Result,
                SecurityGuard,
                ToolDefinition,
                tool,
            ]
        )
