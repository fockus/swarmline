"""Graph context builder — enriches agent system prompt with graph position."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cognitia.multi_agent.graph_task_types import GoalAncestry
from cognitia.multi_agent.graph_types import AgentNode


@dataclass(frozen=True)
class GraphContextSnapshot:
    """Full context for an agent in the graph."""

    agent_node: AgentNode
    chain_of_command: tuple[str, ...] = ()  # agent names from root to self
    goal_ancestry: GoalAncestry | None = None
    sibling_agents: tuple[str, ...] = ()
    child_agents: tuple[str, ...] = ()
    available_tools: tuple[str, ...] = ()
    shared_knowledge: str = ""


class GraphContextBuilder:
    """Builds rich context snapshots for agents in the graph.

    Uses AgentGraphQuery for traversal and optional GraphTaskBoard for goals.
    """

    def __init__(
        self,
        graph_query: Any,
        task_board: Any | None = None,
        token_budget: int = 4000,
    ) -> None:
        self._graph = graph_query
        self._task_board = task_board
        self._token_budget = token_budget

    async def build_context(
        self,
        agent_id: str,
        *,
        task_id: str | None = None,
        shared_knowledge: str = "",
    ) -> GraphContextSnapshot:
        """Build a full context snapshot for the given agent."""
        node = await self._graph.get_node(agent_id)
        if node is None:
            raise ValueError(f"Agent '{agent_id}' not found in graph")

        # Chain of command (root to self)
        chain = await self._graph.get_chain_of_command(agent_id)
        chain_names = tuple(n.name for n in reversed(chain))

        # Siblings (same parent)
        siblings: tuple[str, ...] = ()
        if node.parent_id:
            parent_children = await self._graph.get_children(node.parent_id)
            siblings = tuple(c.name for c in parent_children if c.id != agent_id)

        # Children
        children = await self._graph.get_children(agent_id)
        child_names = tuple(c.name for c in children)

        # Tools: own + inherited from ancestors
        tools = list(node.allowed_tools)
        for ancestor in chain[1:]:  # skip self
            for tool in ancestor.allowed_tools:
                if tool not in tools:
                    tools.append(tool)

        # Goal ancestry
        goal_ancestry: GoalAncestry | None = None
        if task_id and self._task_board:
            goal_ancestry = await self._task_board.get_goal_ancestry(task_id)

        return GraphContextSnapshot(
            agent_node=node,
            chain_of_command=chain_names,
            goal_ancestry=goal_ancestry,
            sibling_agents=siblings,
            child_agents=child_names,
            available_tools=tuple(tools),
            shared_knowledge=shared_knowledge,
        )

    def render_system_prompt(self, snapshot: GraphContextSnapshot) -> str:
        """Render a structured system prompt from the context snapshot."""
        sections: list[str] = []
        node = snapshot.agent_node

        # Identity
        sections.append(f"## Your Identity\nYou are {node.name}, role: {node.role}.")

        # Chain of command
        if snapshot.chain_of_command:
            chain_str = " > ".join(snapshot.chain_of_command)
            sections.append(f"## Chain of Command\n{chain_str}")

        # Current task & goal
        if snapshot.goal_ancestry:
            chain_str = " > ".join(snapshot.goal_ancestry.chain)
            sections.append(f"## Goal Ancestry\n{chain_str}")

        # Team
        team_lines: list[str] = []
        if snapshot.sibling_agents:
            team_lines.append(f"Peers: {', '.join(snapshot.sibling_agents)}")
        if snapshot.child_agents:
            team_lines.append(f"Reports to you: {', '.join(snapshot.child_agents)}")
        if team_lines:
            sections.append("## Your Team\n" + "\n".join(team_lines))

        # Tools
        if snapshot.available_tools:
            sections.append(f"## Available Tools\n{', '.join(snapshot.available_tools)}")

        # Instructions
        if node.system_prompt:
            sections.append(f"## Your Instructions\n{node.system_prompt}")

        # Shared knowledge (truncate if over budget)
        if snapshot.shared_knowledge:
            knowledge = snapshot.shared_knowledge
            # Simple truncation — cut to budget
            max_chars = self._token_budget * 3  # rough estimate: ~3 chars per token
            if len(knowledge) > max_chars:
                knowledge = knowledge[:max_chars] + "\n...(truncated)"
            sections.append(f"## Shared Knowledge\n{knowledge}")

        return "\n\n".join(sections)
