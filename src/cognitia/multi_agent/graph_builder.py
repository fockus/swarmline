"""Fluent builder for constructing agent graphs from code, dicts, or YAML."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cognitia.multi_agent.graph_types import AgentNode, GraphSnapshot


class GraphBuilder:
    """Fluent API for building agent graphs.

    Usage:
        builder = GraphBuilder(store)
        builder.add_root("ceo", "CEO", "executive", system_prompt="You lead.")
        builder.add_child("cto", "ceo", "CTO", "tech_lead")
        builder.add_child("eng1", "cto", "Engineer 1", "engineer")
        snapshot = await builder.build()

    Or from a dict/YAML:
        snapshot = await GraphBuilder.from_dict(config, store)
        snapshot = await GraphBuilder.from_yaml("org.yaml", store)
    """

    def __init__(self, store: Any) -> None:
        self._store = store
        self._queue: list[AgentNode] = []

    def add_root(
        self,
        id: str,
        name: str,
        role: str,
        *,
        system_prompt: str = "",
        allowed_tools: tuple[str, ...] = (),
        skills: tuple[str, ...] = (),
        runtime_config: dict[str, Any] | None = None,
        budget_limit_usd: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> GraphBuilder:
        self._queue.append(AgentNode(
            id=id,
            name=name,
            role=role,
            parent_id=None,
            system_prompt=system_prompt,
            allowed_tools=allowed_tools,
            skills=skills,
            runtime_config=runtime_config,
            budget_limit_usd=budget_limit_usd,
            metadata=metadata or {},
        ))
        return self

    def add_child(
        self,
        id: str,
        parent_id: str,
        name: str,
        role: str,
        *,
        system_prompt: str = "",
        allowed_tools: tuple[str, ...] = (),
        skills: tuple[str, ...] = (),
        runtime_config: dict[str, Any] | None = None,
        budget_limit_usd: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> GraphBuilder:
        self._queue.append(AgentNode(
            id=id,
            name=name,
            role=role,
            parent_id=parent_id,
            system_prompt=system_prompt,
            allowed_tools=allowed_tools,
            skills=skills,
            runtime_config=runtime_config,
            budget_limit_usd=budget_limit_usd,
            metadata=metadata or {},
        ))
        return self

    async def build(self) -> GraphSnapshot:
        """Flush queued nodes to the store and return a snapshot."""
        for node in self._queue:
            await self._store.add_node(node)
        self._queue.clear()
        return await self._store.snapshot()

    @classmethod
    async def from_dict(cls, config: dict[str, Any], store: Any) -> GraphSnapshot:
        """Build a graph from a nested dict structure.

        Expected format:
            {
                "id": "ceo", "name": "CEO", "role": "executive",
                "system_prompt": "...", "allowed_tools": [...],
                "children": [
                    {"id": "cto", "name": "CTO", "role": "tech_lead", "children": [...]},
                ]
            }
        """
        builder = cls(store)
        cls._add_from_dict(builder, config, parent_id=None)
        return await builder.build()

    @classmethod
    def _add_from_dict(cls, builder: GraphBuilder, node: dict, parent_id: str | None) -> None:
        kwargs: dict[str, Any] = {
            "system_prompt": node.get("system_prompt", ""),
            "allowed_tools": tuple(node.get("allowed_tools", ())),
            "skills": tuple(node.get("skills", ())),
            "runtime_config": node.get("runtime_config"),
            "budget_limit_usd": node.get("budget_limit_usd"),
            "metadata": node.get("metadata", {}),
        }
        if parent_id is None:
            builder.add_root(node["id"], node["name"], node["role"], **kwargs)
        else:
            builder.add_child(node["id"], parent_id, node["name"], node["role"], **kwargs)
        for child in node.get("children", []):
            cls._add_from_dict(builder, child, parent_id=node["id"])

    @classmethod
    async def from_yaml(cls, path: str | Path, store: Any) -> GraphSnapshot:
        """Build a graph from a YAML file."""
        import yaml  # lazy import — yaml is optional

        content = Path(path).read_text()
        config = yaml.safe_load(content)
        return await cls.from_dict(config, store)
