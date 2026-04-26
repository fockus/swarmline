"""Tests for MCP plan tools."""

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
def session() -> StatefulSession:
    return StatefulSession(mode="headless")


# ---------------------------------------------------------------------------
# Create & Get
# ---------------------------------------------------------------------------


class TestPlanCreate:
    async def test_create_plan_returns_ok_with_structure(
        self, session: StatefulSession
    ) -> None:
        result = await plan_create(
            session, "Build API", ["Design schema", "Implement endpoints"]
        )
        assert result["ok"] is True
        data = result["data"]
        assert data["goal"] == "Build API"
        assert data["status"] == "draft"
        assert len(data["steps"]) == 2
        assert data["steps"][0]["description"] == "Design schema"
        assert data["steps"][1]["description"] == "Implement endpoints"
        assert data["steps"][0]["status"] == "pending"

    async def test_create_plan_assigns_unique_ids(
        self, session: StatefulSession
    ) -> None:
        r1 = await plan_create(session, "Plan A", ["step1"])
        r2 = await plan_create(session, "Plan B", ["step1"])
        assert r1["data"]["id"] != r2["data"]["id"]

    async def test_create_plan_with_custom_namespace(
        self, session: StatefulSession
    ) -> None:
        result = await plan_create(
            session, "Scoped plan", ["s1"], user_id="alice", topic_id="project-x"
        )
        assert result["ok"] is True
        plans = await plan_list(session, user_id="alice", topic_id="project-x")
        assert len(plans["data"]) == 1
        assert plans["data"][0]["id"] == result["data"]["id"]


class TestPlanGet:
    async def test_get_existing_plan(self, session: StatefulSession) -> None:
        created = await plan_create(session, "Goal", ["step"])
        plan_id = created["data"]["id"]
        result = await plan_get(session, plan_id)
        assert result["ok"] is True
        assert result["data"]["goal"] == "Goal"

    async def test_get_nonexistent_plan_returns_error(
        self, session: StatefulSession
    ) -> None:
        result = await plan_get(session, "nonexistent-id")
        assert result["ok"] is False
        assert "not found" in result["error"].lower()


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


class TestPlanList:
    async def test_list_plans_empty(self, session: StatefulSession) -> None:
        result = await plan_list(session, user_id="nobody", topic_id="nothing")
        assert result["ok"] is True
        assert result["data"] == []

    async def test_list_plans_filters_by_namespace(
        self, session: StatefulSession
    ) -> None:
        await plan_create(session, "A", ["s1"], user_id="u1", topic_id="t1")
        await plan_create(session, "B", ["s1"], user_id="u2", topic_id="t2")
        r1 = await plan_list(session, user_id="u1", topic_id="t1")
        assert len(r1["data"]) == 1
        assert r1["data"][0]["goal"] == "A"


# ---------------------------------------------------------------------------
# Approve
# ---------------------------------------------------------------------------


class TestPlanApprove:
    async def test_approve_draft_plan_transitions_to_approved(
        self, session: StatefulSession
    ) -> None:
        created = await plan_create(session, "Goal", ["step"])
        plan_id = created["data"]["id"]
        result = await plan_approve(session, plan_id, approved_by="user")
        assert result["ok"] is True
        assert result["data"]["status"] == "approved"
        assert result["data"]["approved_by"] == "user"

    async def test_approve_already_approved_plan_returns_error(
        self, session: StatefulSession
    ) -> None:
        created = await plan_create(session, "Goal", ["step"])
        plan_id = created["data"]["id"]
        await plan_approve(session, plan_id)
        result = await plan_approve(session, plan_id)
        assert result["ok"] is False
        assert "draft" in result["error"].lower()

    async def test_approve_nonexistent_plan_returns_error(
        self, session: StatefulSession
    ) -> None:
        result = await plan_approve(session, "ghost-plan")
        assert result["ok"] is False
        assert "not found" in result["error"].lower()


# ---------------------------------------------------------------------------
# Update Step
# ---------------------------------------------------------------------------


class TestPlanUpdateStep:
    async def test_update_step_to_in_progress(self, session: StatefulSession) -> None:
        created = await plan_create(session, "Goal", ["do thing"])
        plan_id = created["data"]["id"]
        step_id = created["data"]["steps"][0]["id"]
        result = await plan_update_step(session, plan_id, step_id, "in_progress")
        assert result["ok"] is True
        assert result["data"]["status"] == "in_progress"

    async def test_update_step_to_completed_with_result(
        self, session: StatefulSession
    ) -> None:
        created = await plan_create(session, "Goal", ["do thing"])
        plan_id = created["data"]["id"]
        step_id = created["data"]["steps"][0]["id"]
        result = await plan_update_step(
            session, plan_id, step_id, "completed", result="done successfully"
        )
        assert result["ok"] is True
        assert result["data"]["status"] == "completed"
        assert result["data"]["result"] == "done successfully"

    async def test_update_step_to_failed(self, session: StatefulSession) -> None:
        created = await plan_create(session, "Goal", ["do thing"])
        plan_id = created["data"]["id"]
        step_id = created["data"]["steps"][0]["id"]
        result = await plan_update_step(
            session, plan_id, step_id, "failed", result="timeout"
        )
        assert result["ok"] is True
        assert result["data"]["status"] == "failed"
        assert result["data"]["result"] == "timeout"

    async def test_update_step_to_skipped(self, session: StatefulSession) -> None:
        created = await plan_create(session, "Goal", ["do thing"])
        plan_id = created["data"]["id"]
        step_id = created["data"]["steps"][0]["id"]
        result = await plan_update_step(
            session, plan_id, step_id, "skipped", result="not needed"
        )
        assert result["ok"] is True
        assert result["data"]["status"] == "skipped"

    async def test_update_step_invalid_status_returns_error(
        self, session: StatefulSession
    ) -> None:
        created = await plan_create(session, "Goal", ["do thing"])
        plan_id = created["data"]["id"]
        step_id = created["data"]["steps"][0]["id"]
        result = await plan_update_step(session, plan_id, step_id, "bogus")
        assert result["ok"] is False
        assert "invalid status" in result["error"].lower()

    async def test_update_step_nonexistent_step_returns_error(
        self, session: StatefulSession
    ) -> None:
        created = await plan_create(session, "Goal", ["do thing"])
        plan_id = created["data"]["id"]
        result = await plan_update_step(session, plan_id, "ghost-step", "completed")
        assert result["ok"] is False
        assert "not found" in result["error"].lower()

    async def test_update_step_nonexistent_plan_returns_error(
        self, session: StatefulSession
    ) -> None:
        result = await plan_update_step(
            session, "ghost-plan", "ghost-step", "completed"
        )
        assert result["ok"] is False
        assert "not found" in result["error"].lower()

    async def test_update_step_persists_in_plan(self, session: StatefulSession) -> None:
        created = await plan_create(session, "Goal", ["step A", "step B"])
        plan_id = created["data"]["id"]
        step_id = created["data"]["steps"][0]["id"]
        await plan_update_step(session, plan_id, step_id, "completed", result="done")
        plan = await plan_get(session, plan_id)
        steps = plan["data"]["steps"]
        assert steps[0]["status"] == "completed"
        assert steps[0]["result"] == "done"
        assert steps[1]["status"] == "pending"
