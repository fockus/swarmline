"""UC4: Resumable Plans -- Plan lifecycle with create, approve, partial execution,
simulated interruption, and resumption.

Headless E2E test: validates plan state machine, step updates, and
resumability without any LLM calls.
"""

from __future__ import annotations

import pytest

from swarmline.mcp._session import StatefulSession
from swarmline.mcp._tools_plans import (
    plan_approve,
    plan_create,
    plan_get,
    plan_list,
    plan_update_step,
)


@pytest.fixture
async def session():
    s = StatefulSession(mode="headless")
    yield s
    await s.cleanup()


PLAN_STEPS = [
    "Set up project structure",
    "Define domain models",
    "Implement repository layer",
    "Add service layer",
    "Write integration tests",
]


async def test_plan_create_and_retrieve(session: StatefulSession):
    """Plan is created with correct goal and step count."""
    res = await plan_create(session, goal="Build user service", steps=PLAN_STEPS)
    assert res["ok"] is True

    plan_data = res["data"]
    assert plan_data["goal"] == "Build user service"
    assert plan_data["status"] == "draft"
    assert len(plan_data["steps"]) == 5

    # Retrieve by ID
    got = await plan_get(session, plan_id=plan_data["id"])
    assert got["ok"] is True
    assert got["data"]["id"] == plan_data["id"]


async def test_plan_approve_transitions_status(session: StatefulSession):
    """Approving a draft plan transitions it to 'approved'."""
    res = await plan_create(session, goal="Deploy v2", steps=["Build", "Test", "Ship"])
    plan_id = res["data"]["id"]

    approved = await plan_approve(session, plan_id=plan_id)
    assert approved["ok"] is True
    assert approved["data"]["status"] == "approved"
    assert approved["data"]["approved_by"] == "user"


async def test_plan_double_approve_fails(session: StatefulSession):
    """Approving an already-approved plan returns an error."""
    res = await plan_create(session, goal="Double approve test", steps=["Step1"])
    plan_id = res["data"]["id"]

    await plan_approve(session, plan_id=plan_id)
    second = await plan_approve(session, plan_id=plan_id)
    assert second["ok"] is False


async def test_plan_resumable_workflow(session: StatefulSession):
    """Full resumable plan: create, approve, partial execution, resume, complete."""
    # Create and approve
    res = await plan_create(session, goal="Build user service", steps=PLAN_STEPS)
    plan_id = res["data"]["id"]
    step_ids = [s["id"] for s in res["data"]["steps"]]

    await plan_approve(session, plan_id=plan_id)

    # Execute first 3 steps
    for i in range(3):
        await plan_update_step(
            session,
            plan_id=plan_id,
            step_id=step_ids[i],
            status="completed",
            result=f"Step {i} done successfully",
        )

    # -- Simulated interruption: re-fetch the plan --
    plan = await plan_get(session, plan_id=plan_id)
    assert plan["ok"] is True
    steps = plan["data"]["steps"]

    # Find first non-completed step (should be index 3)
    pending = [s for s in steps if s["status"] != "completed"]
    assert len(pending) == 2
    assert pending[0]["description"] == "Add service layer"

    # Resume: complete remaining steps
    for step in pending:
        await plan_update_step(
            session,
            plan_id=plan_id,
            step_id=step["id"],
            status="completed",
            result=f"Resumed and completed: {step['description']}",
        )

    # Verify all steps completed
    final = await plan_get(session, plan_id=plan_id)
    assert final["ok"] is True
    assert all(s["status"] == "completed" for s in final["data"]["steps"])


async def test_plan_list_returns_created_plans(session: StatefulSession):
    """plan_list returns all plans in the namespace."""
    await plan_create(session, goal="Plan A", steps=["S1"])
    await plan_create(session, goal="Plan B", steps=["S1", "S2"])

    listed = await plan_list(session)
    assert listed["ok"] is True
    assert len(listed["data"]) == 2
    goals = {p["goal"] for p in listed["data"]}
    assert goals == {"Plan A", "Plan B"}
