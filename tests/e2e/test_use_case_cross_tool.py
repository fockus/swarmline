"""UC6: Cross-Tool Orchestration -- Shared plan + memory + tasks between
2 agents collaborating on feature development.

Headless E2E test: validates that plans, tasks, and memory interoperate
correctly in a multi-agent workflow without any LLM calls.
"""

from __future__ import annotations

import pytest

from swarmline.mcp._session import StatefulSession
from swarmline.mcp._tools_memory import memory_get_facts, memory_upsert_fact
from swarmline.mcp._tools_plans import (
    plan_approve,
    plan_create,
    plan_get,
    plan_update_step,
)
from swarmline.mcp._tools_team import (
    team_claim_task,
    team_create_task,
    team_list_tasks,
    team_register_agent,
)

PLAN_GOAL = "Add user authentication"
PLAN_STEPS = [
    "Design login UI components",
    "Implement JWT token service",
    "Create login API endpoint",
    "Wire frontend to backend auth",
]

AGENTS = [
    ("frontend-dev", "Frontend Developer", "developer"),
    ("backend-dev", "Backend Developer", "developer"),
]

# Map task IDs to plan step indices for traceability
TASK_DEFS = [
    ("task-ui-design", "Design login UI components", "Create form, validation, error states", "HIGH"),
    ("task-jwt", "Implement JWT token service", "Token generation, refresh, validation", "CRITICAL"),
    ("task-api", "Create login API endpoint", "POST /auth/login with rate limiting", "HIGH"),
    ("task-wire", "Wire frontend to backend auth", "Auth context, interceptors, redirect", "MEDIUM"),
]


@pytest.fixture
async def session():
    s = StatefulSession(mode="headless")
    yield s
    await s.cleanup()


async def test_cross_tool_plan_drives_tasks(session: StatefulSession):
    """Plan steps generate tasks that are tracked independently."""
    res = await plan_create(session, goal=PLAN_GOAL, steps=PLAN_STEPS)
    assert res["ok"] is True
    plan_id = res["data"]["id"]

    await plan_approve(session, plan_id=plan_id)

    for tid, title, desc, prio in TASK_DEFS:
        task_res = await team_create_task(
            session, id=tid, title=title, description=desc, priority=prio,
        )
        assert task_res["ok"] is True

    tasks = await team_list_tasks(session)
    assert tasks["ok"] is True
    assert len(tasks["data"]) == 4


async def test_cross_tool_agents_share_memory(session: StatefulSession):
    """Frontend stores findings that backend can read."""
    namespace = "auth-feature"

    # Frontend stores UI decisions
    await memory_upsert_fact(
        session, user_id=namespace, key="ui-framework", value="React Hook Form for login",
    )
    await memory_upsert_fact(
        session, user_id=namespace, key="ui-state", value="Zustand auth store",
    )

    # Backend reads and adds its own findings
    facts = await memory_get_facts(session, user_id=namespace)
    assert facts["ok"] is True
    assert len(facts["data"]) == 2

    await memory_upsert_fact(
        session, user_id=namespace, key="jwt-algo", value="RS256 with 15min expiry",
    )
    await memory_upsert_fact(
        session, user_id=namespace, key="api-rate-limit", value="5 attempts per minute per IP",
    )

    # All 4 findings visible
    all_facts = await memory_get_facts(session, user_id=namespace)
    assert all_facts["ok"] is True
    assert len(all_facts["data"]) == 4


async def test_cross_tool_full_workflow(session: StatefulSession):
    """End-to-end: plan -> approve -> register agents -> create tasks ->
    claim -> execute -> store findings -> update plan steps -> verify."""
    namespace = "auth-feature-full"

    # 1. Create and approve plan
    plan_res = await plan_create(session, goal=PLAN_GOAL, steps=PLAN_STEPS)
    plan_id = plan_res["data"]["id"]
    step_ids = [s["id"] for s in plan_res["data"]["steps"]]
    await plan_approve(session, plan_id=plan_id)

    # 2. Register agents
    for agent_id, name, role in AGENTS:
        await team_register_agent(session, id=agent_id, name=name, role=role)

    # 3. Create tasks (map to plan steps by index)
    step_to_task: dict[int, str] = {}
    for i, (tid, title, desc, prio) in enumerate(TASK_DEFS):
        await team_create_task(session, id=tid, title=title, description=desc, priority=prio)
        step_to_task[i] = tid

    # 4. Claim and process all tasks
    claimed_tasks: list[str] = []
    for _ in range(4):
        claim = await team_claim_task(session)
        assert claim["ok"] is True
        task_id = claim["data"]["task_id"]
        claimed_tasks.append(task_id)

        # Store finding for this task
        await memory_upsert_fact(
            session,
            user_id=namespace,
            key=f"finding-{task_id}",
            value=f"Completed {task_id} successfully",
        )

    assert len(claimed_tasks) == 4

    # 5. Update plan steps as completed
    for i, step_id in enumerate(step_ids):
        result_text = f"Task {step_to_task[i]} completed"
        res = await plan_update_step(
            session, plan_id=plan_id, step_id=step_id, status="completed", result=result_text,
        )
        assert res["ok"] is True

    # 6. Verify: plan fully done
    final_plan = await plan_get(session, plan_id=plan_id)
    assert final_plan["ok"] is True
    assert all(s["status"] == "completed" for s in final_plan["data"]["steps"])

    # 7. Verify: all tasks claimed (none left)
    no_more = await team_claim_task(session)
    assert no_more["ok"] is False

    # 8. Verify: memory has findings from both agents' work
    facts = await memory_get_facts(session, user_id=namespace)
    assert facts["ok"] is True
    assert len(facts["data"]) == 4
