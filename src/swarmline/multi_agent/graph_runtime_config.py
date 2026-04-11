"""Runtime config inheritance — resolve per-node or inherited from ancestors."""

from __future__ import annotations

from typing import Any


class GraphRuntimeResolver:
    """Resolves runtime config for an agent node via inheritance.

    Walks up the chain of command to find the nearest configured ancestor.
    Falls back to default config if no ancestor has a config.
    """

    def __init__(self, graph_query: Any, default_config: dict[str, Any] | None = None) -> None:
        self._graph = graph_query
        self._default = default_config or {}

    async def resolve(self, agent_id: str) -> dict[str, Any]:
        """Return the effective runtime config for the given agent.

        Priority: node's own config > nearest ancestor's config > default.
        """
        chain = await self._graph.get_chain_of_command(agent_id)
        for node in chain:
            if node.runtime_config is not None:
                return node.runtime_config
        return dict(self._default)
