"""Integration: Agent Facade - full pipeline sborki komponotntov. Verifies chto Agent, AgentConfig, @tool, Middleware correctly
are assembled vmeste cherez real komponotnty cognitia.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from cognitia.agent import (
    Agent,
    AgentConfig,
    Conversation,
    CostTracker,
    SecurityGuard,
    tool,
)
from cognitia.hooks.registry import HookRegistry
from conftest import FakeStreamEvent

# ---------------------------------------------------------------------------
# Full pipeline: Agent + tools + hooks + middleware
# ---------------------------------------------------------------------------


class TestAgentFullPipeline:
    """Agent + vse komponotnty -> query -> Result."""

    @pytest.mark.asyncio
    async def test_config_to_agent_with_all_features(self) -> None:
        """AgentConfig so vsemi fichami -> Agent sozdaetsya without oshibok."""

        @tool(name="calc", description="Calculator")
        async def calc(expr: str) -> str:
            return "42"

        hooks = HookRegistry()

        async def noop(**kwargs: Any) -> dict[str, Any]:
            return {"continue_": True}

        hooks.on_pre_tool_use(noop)

        tracker = CostTracker(budget_usd=10.0)
        guard = SecurityGuard(block_patterns=["rm -rf"])

        config = AgentConfig(
            system_prompt="Ты — помощник",
            model="sonnet",
            tools=(calc.__tool_definition__,),
            middleware=(tracker, guard),
            hooks=hooks,
            max_budget_usd=10.0,
            output_format={"type": "json_schema", "schema": {"type": "object"}},
            betas=("context-1m-2025-08-07",),
            env={"KEY": "val"},
        )

        agent = Agent(config)
        assert len(agent.config.tools) == 1
        assert agent.config.tools[0].name == "calc"
        assert len(agent.config.middleware) == 2

    @pytest.mark.asyncio
    async def test_middleware_chain_integration(self) -> None:
        """CostTracker + SecurityGuard -> Agent -> query cherez mock stream."""

        tracker = CostTracker(budget_usd=5.0)
        guard = SecurityGuard(block_patterns=["DROP TABLE"])

        config = AgentConfig(
            system_prompt="test",
            middleware=(tracker, guard),
        )
        agent = Agent(config)

        # Mock stream
        async def fake_stream(prompt):
            yield FakeStreamEvent(
                "done",
                text="result",
                is_final=True,
                total_cost_usd=0.5,
            )

        with patch.object(agent, "_execute_stream", side_effect=fake_stream):
            result = await agent.query("hello")

        assert result.ok is True
        assert result.text == "result"
        assert tracker.total_cost_usd == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_tools_registration_pipeline(self) -> None:
        """@tool → AgentConfig → Agent.config.tools contain tool spec."""

        @tool(name="greet", description="Greet user")
        async def greet(name: str) -> str:
            return f"Hello, {name}!"

        @tool(name="farewell", description="Say goodbye")
        async def farewell(name: str) -> str:
            return f"Bye, {name}!"

        config = AgentConfig(
            system_prompt="test",
            tools=(greet.__tool_definition__, farewell.__tool_definition__),
        )
        agent = Agent(config)

        tool_names = [t.name for t in agent.config.tools]
        assert "greet" in tool_names
        assert "farewell" in tool_names

        # Tool specs valid
        for td in agent.config.tools:
            spec = td.to_tool_spec()
            assert spec.is_local is True
            assert spec.parameters["type"] == "object"


class TestAgentConfigToOptionsBuilder:
    """AgentConfig -> ClaudeOptionsBuilder.build() - probrasyvanie parameterov."""

    def test_config_resolves_model(self) -> None:
        """Model alias → resolved model."""
        config = AgentConfig(system_prompt="test", model="sonnet")
        assert config.resolved_model.startswith("claude-sonnet")

    def test_config_with_betas_and_budget(self) -> None:
        """Betas and budget from config available."""
        config = AgentConfig(
            system_prompt="test",
            betas=("context-1m-2025-08-07",),
            max_budget_usd=5.0,
            max_thinking_tokens=32000,
        )
        assert config.betas == ("context-1m-2025-08-07",)
        assert config.max_budget_usd == 5.0
        assert config.max_thinking_tokens == 32000


class TestConversationPipeline:
    """Conversation multi-turn cherez mock adapter."""

    @pytest.mark.asyncio
    async def test_conversation_3_turns(self) -> None:
        """3 turn conversation → history grows to 6 messages."""
        agent = Agent(AgentConfig(system_prompt="test"))
        conv = Conversation(agent=agent)

        turn = 0

        async def fake_execute(prompt):
            nonlocal turn
            turn += 1

            yield FakeStreamEvent("text_delta", text=f"Reply {turn}")
            yield FakeStreamEvent(
                "done",
                text=f"Reply {turn}",
                is_final=True,
                total_cost_usd=0.01 * turn,
            )

        with patch.object(conv, "_execute", side_effect=fake_execute):
            r1 = await conv.say("Q1")
            r2 = await conv.say("Q2")
            r3 = await conv.say("Q3")

        assert r1.text == "Reply 1"
        assert r2.text == "Reply 2"
        assert r3.text == "Reply 3"
        assert len(conv.history) == 6  # 3 user + 3 assistant

    @pytest.mark.asyncio
    async def test_conversation_with_middleware(self) -> None:
        """Middleware applied in kazhdyy turn conversation."""
        tracker = CostTracker(budget_usd=10.0)
        config = AgentConfig(system_prompt="test", middleware=(tracker,))
        agent = Agent(config)
        conv = Conversation(agent=agent)

        async def fake_execute(prompt):
            yield FakeStreamEvent(
                "done",
                text="ok",
                is_final=True,
                total_cost_usd=1.0,
            )

        with patch.object(conv, "_execute", side_effect=fake_execute):
            await conv.say("turn 1")
            await conv.say("turn 2")

        assert tracker.total_cost_usd == pytest.approx(2.0)


class TestHooksMerging:
    """Merge hooks from config.hooks + middleware.get_hooks()."""

    def test_merge_config_and_middleware_hooks(self) -> None:
        """Hooks from config + SecurityGuard -> merged registry."""
        config_hooks = HookRegistry()

        async def noop(**kwargs: Any) -> dict[str, Any]:
            return {"continue_": True}

        config_hooks.on_post_tool_use(noop)

        guard = SecurityGuard(block_patterns=["rm -rf"])

        config = AgentConfig(
            system_prompt="test",
            hooks=config_hooks,
            middleware=(guard,),
        )
        agent = Agent(config)
        conv = Conversation(agent=agent)

        merged = conv._merge_hooks()
        assert merged is not None
        events = merged.list_events()
        assert "PostToolUse" in events  # from config
        assert "PreToolUse" in events  # from SecurityGuard
