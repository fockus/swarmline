"""Graph agent tools — hire, delegate, escalate.

Factory function ``create_graph_tools`` returns a list of ToolDefinition
objects that agents can invoke to dynamically modify the org graph, delegate
work, or escalate issues up the chain of command.
"""

from __future__ import annotations

import uuid
from typing import Any

from swarmline.agent.tool import ToolDefinition, tool
from swarmline.multi_agent.graph_orchestrator_types import DelegationRequest
from swarmline.multi_agent.graph_types import AgentNode


def create_graph_tools(
    graph: Any,  # AgentGraphStore + AgentGraphQuery in practice
    task_board: Any,  # GraphTaskBoard
    orchestrator: Any,  # GraphOrchestrator
    *,
    approval_gate: Any | None = None,
    communication: Any | None = None,
    governance: Any | None = None,
) -> list[ToolDefinition]:
    """Create the standard set of graph management tools.

    Args:
        graph: AgentGraphStore for node management.
        task_board: GraphTaskBoard for task tracking.
        orchestrator: GraphOrchestrator for delegation.
        approval_gate: Optional ApprovalGate for hire governance.
        communication: Optional GraphCommunication for escalation messaging.
        governance: Optional GraphGovernanceConfig for global limits.

    Returns:
        List of ToolDefinition objects ready for runtime consumption.
    """

    # -----------------------------------------------------------------
    # hire_agent
    # -----------------------------------------------------------------

    @tool(
        name="graph_hire_agent",
        description="Dynamically create a new agent node in the org graph.",
    )
    async def hire_agent(
        name: str,
        role: str,
        parent_id: str,
        system_prompt: str = "",
        allowed_tools: str = "",
    ) -> str:
        """Create a new agent node under the given parent.

        Args:
            name: Human-readable agent name.
            role: Agent role (e.g. engineer, designer).
            parent_id: ID of the parent node to attach to.
            system_prompt: Instructions for the new agent.
            allowed_tools: Comma-separated tool names.
        """
        # Validate parent exists
        parent = await graph.get_node(parent_id)
        if parent is None:
            return f"Error: parent agent '{parent_id}' not found in graph."

        # Governance check
        if governance is not None:
            from swarmline.multi_agent.graph_governance import check_hire_allowed

            error = await check_hire_allowed(governance, parent, graph)
            if error:
                return f"Governance denied: {error}"

        # Approval gate
        if approval_gate is not None:
            approved = await approval_gate.check(
                "hire_agent",
                {"name": name, "role": role, "parent_id": parent_id},
            )
            if not approved:
                return f"Denied: hiring '{name}' was rejected by approval gate."

        agent_id = uuid.uuid4().hex[:10]
        tools_tuple = tuple(t.strip() for t in allowed_tools.split(",") if t.strip()) if allowed_tools else ()

        node = AgentNode(
            id=agent_id,
            name=name,
            role=role,
            parent_id=parent_id,
            system_prompt=system_prompt,
            allowed_tools=tools_tuple,
        )
        await graph.add_node(node)
        return f"Hired: agent '{name}' (id={agent_id}) created under '{parent.name}'."

    # -----------------------------------------------------------------
    # delegate_task
    # -----------------------------------------------------------------

    @tool(
        name="graph_delegate_task",
        description="Delegate a task to a specific agent in the org graph.",
    )
    async def delegate_task(
        agent_id: str,
        goal: str,
        parent_task_id: str = "",
        caller_agent_id: str = "",
        stage: str = "",
    ) -> str:
        """Delegate a task to an agent via the orchestrator.

        Args:
            agent_id: Target agent to assign the task to.
            goal: Description of what the agent should accomplish.
            parent_task_id: Optional parent task for hierarchy.
            caller_agent_id: Agent performing the delegation (for governance).
            stage: Optional workflow stage name for the task.
        """
        # Governance check on the caller
        if governance is not None and caller_agent_id:
            from swarmline.multi_agent.graph_governance import check_delegate_allowed

            caller = await graph.get_node(caller_agent_id)
            if caller is not None:
                error = check_delegate_allowed(governance, caller)
                if error:
                    return f"Governance denied: {error}"

        # Validate target agent exists
        node = await graph.get_node(agent_id)
        if node is None:
            return f"Error: agent '{agent_id}' not found in graph."

        task_id = f"task-{uuid.uuid4().hex[:10]}"
        req = DelegationRequest(
            task_id=task_id,
            agent_id=agent_id,
            goal=goal,
            parent_task_id=parent_task_id or None,
            stage=stage,
        )
        await orchestrator.delegate(req)
        return f"Delegated: task '{task_id}' assigned to '{node.name}' — {goal}"

    # -----------------------------------------------------------------
    # escalate
    # -----------------------------------------------------------------

    @tool(
        name="graph_escalate",
        description="Escalate an issue to all ancestors in the chain of command.",
    )
    async def escalate(
        from_agent_id: str,
        message: str,
        task_id: str = "",
    ) -> str:
        """Escalate an issue up the chain of command.

        Args:
            from_agent_id: Agent raising the escalation.
            message: Description of the issue.
            task_id: Optional task ID for context threading.
        """
        node = await graph.get_node(from_agent_id)
        if node is None:
            return f"Error: agent '{from_agent_id}' not found in graph."

        if communication is not None:
            await communication.escalate(
                from_agent_id, message, task_id=task_id or None,
            )
        else:
            # Fallback: walk chain manually and log
            chain = await graph.get_chain_of_command(from_agent_id)
            ancestor_names = [n.name for n in chain[1:]]
            return (
                f"Escalated from '{node.name}': {message} "
                f"(notified: {', '.join(ancestor_names) or 'none'})"
            )

        chain = await graph.get_chain_of_command(from_agent_id)
        ancestor_names = [n.name for n in chain[1:]]
        return (
            f"Escalated from '{node.name}': {message} "
            f"(notified: {', '.join(ancestor_names)})"
        )

    return [
        hire_agent.__tool_definition__,  # type: ignore[attr-defined]
        delegate_task.__tool_definition__,  # type: ignore[attr-defined]
        escalate.__tool_definition__,  # type: ignore[attr-defined]
    ]
