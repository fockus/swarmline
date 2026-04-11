"""Agent registry: track, manage, and query registered agents.

Demonstrates: InMemoryAgentRegistry, AgentRecord, AgentStatus, AgentFilter.
No API keys required.
"""

import asyncio

from swarmline.multi_agent.agent_registry import (
    AgentFilter,
    AgentRecord,
    AgentStatus,
    InMemoryAgentRegistry,
)


async def main() -> None:
    registry = InMemoryAgentRegistry()

    # 1. Register agents with roles and hierarchy
    print("=== Register Agents ===")
    agents = [
        AgentRecord(
            id="lead-1", name="Team Lead", role="lead",
            runtime_name="thin", budget_limit_usd=10.0,
        ),
        AgentRecord(
            id="dev-1", name="Backend Dev", role="developer",
            parent_id="lead-1", runtime_name="thin",
            metadata={"lang": "python", "specialty": "api"},
        ),
        AgentRecord(
            id="dev-2", name="Frontend Dev", role="developer",
            parent_id="lead-1", runtime_name="thin",
            metadata={"lang": "typescript", "specialty": "ui"},
        ),
        AgentRecord(
            id="reviewer-1", name="Code Reviewer", role="reviewer",
            parent_id="lead-1", runtime_name="thin",
        ),
        AgentRecord(
            id="researcher-1", name="Researcher", role="researcher",
            runtime_name="thin", status=AgentStatus.RUNNING,
        ),
    ]
    for agent in agents:
        await registry.register(agent)
        print(f"  Registered: {agent.name} (role={agent.role}, parent={agent.parent_id or 'root'})")

    # 2. Query by filters
    print("\n=== Query Agents ===")
    all_agents = await registry.list_agents()
    print(f"Total agents: {len(all_agents)}")

    devs = await registry.list_agents(AgentFilter(role="developer"))
    print(f"Developers: {[a.name for a in devs]}")

    team = await registry.list_agents(AgentFilter(parent_id="lead-1"))
    print(f"Lead's team: {[a.name for a in team]}")

    running = await registry.list_agents(AgentFilter(status=AgentStatus.RUNNING))
    print(f"Running: {[a.name for a in running]}")

    # 3. Update lifecycle status
    print("\n=== Lifecycle Management ===")
    await registry.update_status("dev-1", AgentStatus.RUNNING)
    dev1 = await registry.get("dev-1")
    print(f"dev-1 status: {dev1.status.value if dev1 else 'not found'}")

    await registry.update_status("dev-1", AgentStatus.STOPPED)
    dev1 = await registry.get("dev-1")
    print(f"dev-1 status: {dev1.status.value if dev1 else 'not found'}")

    # 4. Get single agent by ID
    print("\n=== Get by ID ===")
    lead = await registry.get("lead-1")
    if lead:
        print(f"Lead: {lead.name}, budget=${lead.budget_limit_usd}")

    missing = await registry.get("nonexistent")
    print(f"Missing agent: {missing}")

    # 5. Remove agent
    print("\n=== Remove Agent ===")
    removed = await registry.remove("reviewer-1")
    print(f"Removed reviewer: {removed}")
    remaining = await registry.list_agents()
    print(f"Remaining: {[a.name for a in remaining]}")

    # 6. Duplicate registration guard
    print("\n=== Duplicate Guard ===")
    try:
        await registry.register(AgentRecord(id="dev-1", name="Duplicate", role="dev"))
    except ValueError as e:
        print(f"Expected error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
