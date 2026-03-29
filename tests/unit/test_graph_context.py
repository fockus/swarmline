"""Unit: GraphContextBuilder and GraphRuntimeResolver."""

from __future__ import annotations

import pytest

from cognitia.multi_agent.graph_context import GraphContextBuilder, GraphContextSnapshot
from cognitia.multi_agent.graph_runtime_config import GraphRuntimeResolver
from cognitia.multi_agent.graph_store import InMemoryAgentGraph
from cognitia.multi_agent.graph_task_board import InMemoryGraphTaskBoard
from cognitia.multi_agent.graph_task_types import GraphTaskItem
from cognitia.multi_agent.graph_types import AgentNode


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def org():
    store = InMemoryAgentGraph()
    await store.add_node(AgentNode(
        id="ceo", name="CEO", role="executive",
        system_prompt="You are the CEO.",
        allowed_tools=("web_search",),
    ))
    await store.add_node(AgentNode(
        id="cto", name="CTO", role="tech_lead",
        parent_id="ceo",
        system_prompt="You lead engineering.",
        allowed_tools=("code_sandbox",),
    ))
    await store.add_node(AgentNode(
        id="eng1", name="Engineer 1", role="engineer",
        parent_id="cto",
    ))
    await store.add_node(AgentNode(
        id="eng2", name="Engineer 2", role="engineer",
        parent_id="cto",
    ))
    return store


# ---------------------------------------------------------------------------
# GraphContextBuilder
# ---------------------------------------------------------------------------


class TestContextBuilder:

    async def test_build_context_for_leaf(self, org) -> None:
        builder = GraphContextBuilder(graph_query=org)
        ctx = await builder.build_context("eng1")
        assert isinstance(ctx, GraphContextSnapshot)
        assert ctx.agent_node.id == "eng1"

    async def test_chain_of_command(self, org) -> None:
        builder = GraphContextBuilder(graph_query=org)
        ctx = await builder.build_context("eng1")
        assert ctx.chain_of_command == ("CEO", "CTO", "Engineer 1")

    async def test_chain_for_root(self, org) -> None:
        builder = GraphContextBuilder(graph_query=org)
        ctx = await builder.build_context("ceo")
        assert ctx.chain_of_command == ("CEO",)

    async def test_siblings(self, org) -> None:
        builder = GraphContextBuilder(graph_query=org)
        ctx = await builder.build_context("eng1")
        assert "Engineer 2" in ctx.sibling_agents

    async def test_children(self, org) -> None:
        builder = GraphContextBuilder(graph_query=org)
        ctx = await builder.build_context("cto")
        assert set(ctx.child_agents) == {"Engineer 1", "Engineer 2"}

    async def test_inherited_tools(self, org) -> None:
        builder = GraphContextBuilder(graph_query=org)
        ctx = await builder.build_context("eng1")
        # eng1 has no own tools, but inherits from CTO and CEO
        assert "code_sandbox" in ctx.available_tools
        assert "web_search" in ctx.available_tools

    async def test_missing_agent_raises(self, org) -> None:
        builder = GraphContextBuilder(graph_query=org)
        with pytest.raises(ValueError, match="not found"):
            await builder.build_context("nonexistent")

    async def test_with_goal_ancestry(self, org) -> None:
        board = InMemoryGraphTaskBoard()
        await board.create_task(GraphTaskItem(id="root-task", title="Root", goal_id="g1"))
        await board.create_task(GraphTaskItem(
            id="sub-task", title="Sub", parent_task_id="root-task", goal_id="g1"
        ))
        builder = GraphContextBuilder(graph_query=org, task_board=board)
        ctx = await builder.build_context("eng1", task_id="sub-task")
        assert ctx.goal_ancestry is not None
        assert ctx.goal_ancestry.root_goal_id == "g1"


# ---------------------------------------------------------------------------
# Render system prompt
# ---------------------------------------------------------------------------


class TestRenderPrompt:

    async def test_render_includes_identity(self, org) -> None:
        builder = GraphContextBuilder(graph_query=org)
        ctx = await builder.build_context("eng1")
        prompt = builder.render_system_prompt(ctx)
        assert "Engineer 1" in prompt
        assert "engineer" in prompt

    async def test_render_includes_chain(self, org) -> None:
        builder = GraphContextBuilder(graph_query=org)
        ctx = await builder.build_context("eng1")
        prompt = builder.render_system_prompt(ctx)
        assert "CEO > CTO > Engineer 1" in prompt

    async def test_render_includes_team(self, org) -> None:
        builder = GraphContextBuilder(graph_query=org)
        ctx = await builder.build_context("eng1")
        prompt = builder.render_system_prompt(ctx)
        assert "Engineer 2" in prompt

    async def test_render_includes_tools(self, org) -> None:
        builder = GraphContextBuilder(graph_query=org)
        ctx = await builder.build_context("eng1")
        prompt = builder.render_system_prompt(ctx)
        assert "web_search" in prompt

    async def test_render_includes_instructions(self, org) -> None:
        builder = GraphContextBuilder(graph_query=org)
        ctx = await builder.build_context("cto")
        prompt = builder.render_system_prompt(ctx)
        assert "You lead engineering" in prompt

    async def test_render_truncates_knowledge(self, org) -> None:
        builder = GraphContextBuilder(graph_query=org, token_budget=10)
        long_knowledge = "x" * 10000
        ctx = await builder.build_context("eng1", shared_knowledge=long_knowledge)
        prompt = builder.render_system_prompt(ctx)
        assert "truncated" in prompt


# ---------------------------------------------------------------------------
# GraphRuntimeResolver
# ---------------------------------------------------------------------------


class TestRuntimeResolver:

    async def test_own_config(self, org) -> None:
        # Add node with explicit config
        await org.add_node(AgentNode(
            id="special", name="Special", role="worker",
            parent_id="cto",
            runtime_config={"model": "claude-opus"},
        ))
        resolver = GraphRuntimeResolver(graph_query=org)
        config = await resolver.resolve("special")
        assert config["model"] == "claude-opus"

    async def test_inherits_from_ancestor(self, org) -> None:
        # CTO has no runtime_config, CEO has no runtime_config
        # But if we add config to CEO...
        # We need a fresh org with config
        store = InMemoryAgentGraph()
        await store.add_node(AgentNode(
            id="ceo", name="CEO", role="exec",
            runtime_config={"model": "sonnet"},
        ))
        await store.add_node(AgentNode(
            id="cto", name="CTO", role="tech", parent_id="ceo",
        ))
        await store.add_node(AgentNode(
            id="eng", name="Eng", role="worker", parent_id="cto",
        ))
        resolver = GraphRuntimeResolver(graph_query=store)
        config = await resolver.resolve("eng")
        assert config["model"] == "sonnet"

    async def test_falls_back_to_default(self, org) -> None:
        resolver = GraphRuntimeResolver(
            graph_query=org,
            default_config={"model": "default-model"},
        )
        config = await resolver.resolve("eng1")
        assert config["model"] == "default-model"

    async def test_nearest_ancestor_wins(self) -> None:
        store = InMemoryAgentGraph()
        await store.add_node(AgentNode(
            id="ceo", name="CEO", role="exec",
            runtime_config={"model": "expensive"},
        ))
        await store.add_node(AgentNode(
            id="cto", name="CTO", role="tech", parent_id="ceo",
            runtime_config={"model": "cheap"},
        ))
        await store.add_node(AgentNode(
            id="eng", name="Eng", role="worker", parent_id="cto",
        ))
        resolver = GraphRuntimeResolver(graph_query=store)
        config = await resolver.resolve("eng")
        assert config["model"] == "cheap"  # CTO's config, not CEO's
