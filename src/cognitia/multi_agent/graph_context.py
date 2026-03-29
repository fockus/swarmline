"""Graph context builder — enriches agent system prompt with graph position."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from cognitia.multi_agent.graph_task_types import GoalAncestry
from cognitia.multi_agent.graph_types import AgentNode

if TYPE_CHECKING:
    from cognitia.multi_agent.graph_execution_context import AgentExecutionContext


@dataclass(frozen=True)
class GraphContextSnapshot:
    """Full context for an agent in the graph."""

    agent_node: AgentNode
    chain_of_command: tuple[str, ...] = ()  # agent names from root to self
    goal_ancestry: GoalAncestry | None = None
    sibling_agents: tuple[str, ...] = ()
    child_agents: tuple[str, ...] = ()
    available_tools: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    mcp_servers: tuple[str, ...] = ()
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

        # Skills: own + inherited from ancestors
        skills = list(node.skills)
        for ancestor in chain[1:]:
            for skill in ancestor.skills:
                if skill not in skills:
                    skills.append(skill)

        # MCP servers: own + inherited from ancestors (dedup by name)
        mcp_servers = list(node.mcp_servers)
        for ancestor in chain[1:]:
            for server in ancestor.mcp_servers:
                if server not in mcp_servers:
                    mcp_servers.append(server)

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
            skills=tuple(skills),
            mcp_servers=tuple(mcp_servers),
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

        # Skills
        if snapshot.skills:
            sections.append(f"## Skills\n{', '.join(snapshot.skills)}")

        # MCP Servers
        if snapshot.mcp_servers:
            sections.append(f"## MCP Servers\n{', '.join(snapshot.mcp_servers)}")

        # Permissions
        caps = getattr(node, "capabilities", None)
        if caps is not None:
            perm_lines = [
                f"- Can hire subordinates: {'Yes' if caps.can_hire else 'No'}",
                f"- Can delegate tasks: {'Yes' if caps.can_delegate else 'No'}",
                f"- Can use subagents: {'Yes' if caps.can_use_subagents else 'No'}",
            ]
            if caps.can_use_team_mode:
                perm_lines.append("- Can use team mode: Yes")
            sections.append("## Your Permissions\n" + "\n".join(perm_lines))

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

    async def build_execution_context(
        self,
        agent_id: str,
        task_id: str,
        goal: str,
        *,
        shared_knowledge: str = "",
    ) -> "AgentExecutionContext":
        """Build a full execution context for the runner."""
        from cognitia.multi_agent.graph_execution_context import AgentExecutionContext

        snapshot = await self.build_context(
            agent_id, task_id=task_id, shared_knowledge=shared_knowledge,
        )
        system_prompt = self.render_system_prompt(snapshot)
        node = snapshot.agent_node

        return AgentExecutionContext(
            agent_id=agent_id,
            task_id=task_id,
            goal=goal,
            system_prompt=system_prompt,
            tools=snapshot.available_tools,
            skills=snapshot.skills,
            mcp_servers=snapshot.mcp_servers,
            runtime_config=node.runtime_config,
            budget_limit_usd=node.budget_limit_usd,
            metadata=node.metadata,
        )
