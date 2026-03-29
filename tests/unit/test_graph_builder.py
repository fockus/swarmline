"""Unit: GraphBuilder — fluent API, from_dict, from_yaml."""

from __future__ import annotations

from pathlib import Path

from cognitia.multi_agent.graph_builder import GraphBuilder
from cognitia.multi_agent.graph_store import InMemoryAgentGraph


# ---------------------------------------------------------------------------
# Fluent API
# ---------------------------------------------------------------------------


class TestFluentAPI:

    async def test_add_root_and_build(self) -> None:
        store = InMemoryAgentGraph()
        builder = GraphBuilder(store)
        builder.add_root("ceo", "CEO", "executive")
        snap = await builder.build()
        assert len(snap.nodes) == 1
        assert snap.root_id == "ceo"

    async def test_chain_returns_self(self) -> None:
        store = InMemoryAgentGraph()
        builder = GraphBuilder(store)
        result = builder.add_root("ceo", "CEO", "executive")
        assert result is builder

    async def test_add_children(self) -> None:
        store = InMemoryAgentGraph()
        builder = GraphBuilder(store)
        builder.add_root("ceo", "CEO", "executive")
        builder.add_child("cto", "ceo", "CTO", "tech_lead")
        builder.add_child("cpo", "ceo", "CPO", "product")
        snap = await builder.build()
        assert len(snap.nodes) == 3
        assert len(snap.edges) == 2

    async def test_deep_hierarchy(self) -> None:
        store = InMemoryAgentGraph()
        builder = GraphBuilder(store)
        builder.add_root("ceo", "CEO", "executive")
        builder.add_child("cto", "ceo", "CTO", "tech_lead")
        builder.add_child("eng1", "cto", "Eng1", "engineer")
        builder.add_child("eng2", "cto", "Eng2", "engineer")
        snap = await builder.build()
        assert len(snap.nodes) == 4
        chain = await store.get_chain_of_command("eng1")
        assert [n.id for n in chain] == ["eng1", "cto", "ceo"]

    async def test_fluent_with_kwargs(self) -> None:
        store = InMemoryAgentGraph()
        snap = await (
            GraphBuilder(store)
            .add_root("ceo", "CEO", "executive", system_prompt="You are CEO")
            .add_child("cto", "ceo", "CTO", "tech", allowed_tools=("web_search",))
            .build()
        )
        assert len(snap.nodes) == 2
        cto = await store.get_node("cto")
        assert cto is not None
        assert cto.allowed_tools == ("web_search",)

    async def test_add_root_with_mcp_servers(self) -> None:
        store = InMemoryAgentGraph()
        builder = GraphBuilder(store)
        builder.add_root(
            "ceo", "CEO", "executive",
            mcp_servers=("filesystem", "github"),
        )
        snap = await builder.build()
        assert snap.nodes[0].mcp_servers == ("filesystem", "github")

    async def test_add_child_with_mcp_servers(self) -> None:
        store = InMemoryAgentGraph()
        builder = GraphBuilder(store)
        builder.add_root("ceo", "CEO", "executive")
        builder.add_child(
            "cto", "ceo", "CTO", "tech",
            mcp_servers=("database",),
        )
        await builder.build()
        cto = await store.get_node("cto")
        assert cto is not None
        assert cto.mcp_servers == ("database",)

    async def test_mcp_servers_default_empty(self) -> None:
        store = InMemoryAgentGraph()
        builder = GraphBuilder(store)
        builder.add_root("ceo", "CEO", "executive")
        snap = await builder.build()
        assert snap.nodes[0].mcp_servers == ()


# ---------------------------------------------------------------------------
# from_dict
# ---------------------------------------------------------------------------


class TestFromDict:

    async def test_simple_dict(self) -> None:
        store = InMemoryAgentGraph()
        config = {
            "id": "ceo",
            "name": "CEO",
            "role": "executive",
            "children": [
                {"id": "cto", "name": "CTO", "role": "tech_lead"},
                {"id": "cpo", "name": "CPO", "role": "product"},
            ],
        }
        snap = await GraphBuilder.from_dict(config, store)
        assert len(snap.nodes) == 3
        assert snap.root_id == "ceo"

    async def test_nested_dict(self) -> None:
        store = InMemoryAgentGraph()
        config = {
            "id": "ceo",
            "name": "CEO",
            "role": "exec",
            "children": [
                {
                    "id": "cto",
                    "name": "CTO",
                    "role": "tech",
                    "children": [
                        {"id": "eng1", "name": "E1", "role": "engineer"},
                        {"id": "eng2", "name": "E2", "role": "engineer"},
                    ],
                }
            ],
        }
        snap = await GraphBuilder.from_dict(config, store)
        assert len(snap.nodes) == 4
        children = await store.get_children("cto")
        assert len(children) == 2

    async def test_dict_with_all_fields(self) -> None:
        store = InMemoryAgentGraph()
        config = {
            "id": "ceo",
            "name": "CEO",
            "role": "exec",
            "system_prompt": "You lead the company",
            "allowed_tools": ["web_search"],
            "skills": ["planning"],
            "budget_limit_usd": 100.0,
        }
        snap = await GraphBuilder.from_dict(config, store)
        node = snap.nodes[0]
        assert node.system_prompt == "You lead the company"
        assert node.allowed_tools == ("web_search",)
        assert node.budget_limit_usd == 100.0

    async def test_from_dict_with_mcp_servers(self) -> None:
        store = InMemoryAgentGraph()
        config = {
            "id": "ceo",
            "name": "CEO",
            "role": "exec",
            "mcp_servers": ["filesystem", "github"],
            "children": [
                {
                    "id": "cto",
                    "name": "CTO",
                    "role": "tech",
                    "mcp_servers": ["database"],
                },
            ],
        }
        snap = await GraphBuilder.from_dict(config, store)
        ceo = snap.nodes[0]
        assert ceo.mcp_servers == ("filesystem", "github")
        cto = await store.get_node("cto")
        assert cto is not None
        assert cto.mcp_servers == ("database",)


# ---------------------------------------------------------------------------
# from_yaml
# ---------------------------------------------------------------------------


class TestFromYaml:

    async def test_yaml_file(self, tmp_path: Path) -> None:
        yaml_content = """\
id: ceo
name: CEO
role: executive
children:
  - id: cto
    name: CTO
    role: tech_lead
  - id: cpo
    name: CPO
    role: product
"""
        path = tmp_path / "org.yaml"
        path.write_text(yaml_content)
        store = InMemoryAgentGraph()
        snap = await GraphBuilder.from_yaml(path, store)
        assert len(snap.nodes) == 3
        assert snap.root_id == "ceo"
