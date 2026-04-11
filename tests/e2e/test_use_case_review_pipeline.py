"""UC3: Code Review Pipeline -- Priority-based task claiming, no double-claim,
aggregate reviews into memory.

Headless E2E test: validates priority ordering, claim atomicity,
and review result aggregation without any LLM calls.
"""

from __future__ import annotations

import pytest

from swarmline.mcp._session import StatefulSession
from swarmline.mcp._tools_memory import memory_get_facts, memory_upsert_fact
from swarmline.mcp._tools_team import (
    team_claim_task,
    team_create_task,
    team_list_tasks,
    team_register_agent,
)


@pytest.fixture
async def session():
    s = StatefulSession(mode="headless")
    yield s
    await s.cleanup()


REVIEWERS = [
    ("reviewer-1", "Senior Reviewer", "reviewer"),
    ("reviewer-2", "Junior Reviewer", "reviewer"),
]

REVIEW_TASKS = [
    ("pr-101", "Review auth module", "Check OWASP top 10", "CRITICAL"),
    ("pr-102", "Review API routes", "REST conventions", "HIGH"),
    ("pr-103", "Review DB migrations", "Check rollback", "MEDIUM"),
    ("pr-104", "Review logging config", "Structured logging check", "LOW"),
    ("pr-105", "Review test coverage", "Coverage thresholds", "HIGH"),
]


async def test_priority_ordering_critical_first(session: StatefulSession):
    """Tasks are claimed in priority order: CRITICAL > HIGH > MEDIUM > LOW."""
    for tid, title, desc, prio in REVIEW_TASKS:
        await team_create_task(session, id=tid, title=title, description=desc, priority=prio)

    first = await team_claim_task(session)
    assert first["ok"] is True
    assert first["data"]["task_id"] == "pr-101"  # CRITICAL

    second = await team_claim_task(session)
    assert second["ok"] is True
    # HIGH priority -- either pr-102 or pr-105
    assert second["data"]["task_id"] in ("pr-102", "pr-105")


async def test_no_double_claim(session: StatefulSession):
    """Once claimed, a task cannot be claimed again."""
    await team_create_task(
        session, id="single-task", title="Solo review", priority="HIGH",
    )

    first = await team_claim_task(session)
    assert first["ok"] is True
    assert first["data"]["task_id"] == "single-task"

    # Second claim should fail -- no more TODO tasks
    second = await team_claim_task(session)
    assert second["ok"] is False


async def test_review_pipeline_full_workflow(session: StatefulSession):
    """Full pipeline: register reviewers, create tasks, claim, review, aggregate."""
    namespace = "code-review"

    # Register reviewers
    for agent_id, name, role in REVIEWERS:
        res = await team_register_agent(session, id=agent_id, name=name, role=role)
        assert res["ok"] is True

    # Create all review tasks
    for tid, title, desc, prio in REVIEW_TASKS:
        res = await team_create_task(
            session, id=tid, title=title, description=desc, priority=prio,
        )
        assert res["ok"] is True

    # Both reviewers claim and process tasks
    claimed_ids: list[str] = []
    for _ in range(len(REVIEW_TASKS)):
        claim = await team_claim_task(session)
        if not claim["ok"]:
            break
        task_id = claim["data"]["task_id"]
        claimed_ids.append(task_id)

        # Store review finding in memory
        await memory_upsert_fact(
            session,
            user_id=namespace,
            key=f"review-{task_id}",
            value=f"Reviewed {task_id}: LGTM with minor comments",
        )

    # All 5 tasks should be claimed (no duplicates)
    assert len(claimed_ids) == 5
    assert len(set(claimed_ids)) == 5

    # No more tasks available
    empty = await team_claim_task(session)
    assert empty["ok"] is False

    # Verify review findings stored
    facts = await memory_get_facts(session, user_id=namespace)
    assert facts["ok"] is True
    assert len(facts["data"]) == 5


async def test_claimed_tasks_show_in_progress(session: StatefulSession):
    """Claimed tasks transition to in_progress status."""
    await team_create_task(
        session, id="status-check", title="Check status", priority="MEDIUM",
    )

    await team_claim_task(session)

    tasks = await team_list_tasks(session, status="in_progress")
    assert tasks["ok"] is True
    assert len(tasks["data"]) == 1
    assert tasks["data"][0]["id"] == "status-check"
    assert tasks["data"][0]["status"] == "in_progress"
