"""UC1: Research Swarm -- 3 agents research different topics, store findings
in shared memory, aggregate results into a summary.

Headless E2E test: validates team registration, task claiming, memory storage,
and aggregation without any LLM calls.
"""

from __future__ import annotations

import pytest

from swarmline.mcp._session import StatefulSession
from swarmline.mcp._tools_memory import (
    memory_get_facts,
    memory_save_summary,
    memory_upsert_fact,
)
from swarmline.mcp._tools_team import (
    team_claim_task,
    team_create_task,
    team_list_agents,
    team_register_agent,
)

AGENTS = [
    ("researcher-api", "API Researcher", "researcher"),
    ("researcher-db", "DB Researcher", "researcher"),
    ("researcher-security", "Security Researcher", "researcher"),
]

TASKS = [
    ("task-api", "Research REST API patterns", "Analyze API design", "HIGH"),
    ("task-db", "Research DB indexing", "Analyze indexing strategies", "MEDIUM"),
    ("task-sec", "Research auth methods", "Analyze OAuth2 vs JWT", "CRITICAL"),
]

FINDINGS = {
    "researcher-api": ("api-patterns", "Use versioned REST with HATEOAS links"),
    "researcher-db": (
        "db-indexing",
        "Composite indexes on hot columns reduce p99 by 40%",
    ),
    "researcher-security": (
        "auth-method",
        "OAuth2 + PKCE for public clients, JWT for service-to-service",
    ),
}


@pytest.fixture
async def session():
    s = StatefulSession(mode="headless")
    yield s
    await s.cleanup()


async def test_research_swarm_agents_register_and_list(session: StatefulSession):
    for agent_id, name, role in AGENTS:
        res = await team_register_agent(session, id=agent_id, name=name, role=role)
        assert res["ok"] is True

    listed = await team_list_agents(session)
    assert listed["ok"] is True
    assert len(listed["data"]) == 3


async def test_research_swarm_tasks_created_and_claimed(session: StatefulSession):
    for agent_id, name, role in AGENTS:
        await team_register_agent(session, id=agent_id, name=name, role=role)

    for task_id, title, desc, priority in TASKS:
        res = await team_create_task(
            session,
            id=task_id,
            title=title,
            description=desc,
            priority=priority,
        )
        assert res["ok"] is True

    # Claim tasks -- highest priority (CRITICAL) comes first
    first_claim = await team_claim_task(session)
    assert first_claim["ok"] is True
    assert first_claim["data"]["task_id"] == "task-sec"

    second_claim = await team_claim_task(session)
    assert second_claim["ok"] is True
    assert second_claim["data"]["task_id"] == "task-api"

    third_claim = await team_claim_task(session)
    assert third_claim["ok"] is True
    assert third_claim["data"]["task_id"] == "task-db"

    # No more tasks to claim
    empty = await team_claim_task(session)
    assert empty["ok"] is False


async def test_research_swarm_full_workflow(session: StatefulSession):
    """Full swarm: register, create tasks, claim, store findings, aggregate."""
    namespace = "research-project"

    # Register agents
    for agent_id, name, role in AGENTS:
        await team_register_agent(session, id=agent_id, name=name, role=role)

    # Create tasks
    for task_id, title, desc, priority in TASKS:
        await team_create_task(
            session,
            id=task_id,
            title=title,
            description=desc,
            priority=priority,
        )

    # Each agent claims a task and stores findings
    for agent_id, (fact_key, fact_value) in FINDINGS.items():
        claim = await team_claim_task(session)
        assert claim["ok"] is True

        res = await memory_upsert_fact(
            session,
            user_id=namespace,
            key=fact_key,
            value=fact_value,
        )
        assert res["ok"] is True

    # Aggregate: retrieve all findings
    facts = await memory_get_facts(session, user_id=namespace)
    assert facts["ok"] is True
    assert len(facts["data"]) >= 3

    # Save summary
    summary_text = "; ".join(f"{k}: {v}" for k, v in FINDINGS.values())
    summary = await memory_save_summary(
        session,
        user_id=namespace,
        topic_id="final-report",
        summary=summary_text,
        messages_covered=3,
    )
    assert summary["ok"] is True
