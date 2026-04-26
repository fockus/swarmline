"""Tests for MCP team coordination tools.

All tests use real StatefulSession with InMemoryAgentRegistry and InMemoryTaskQueue.
No mocks.
"""

from __future__ import annotations

import pytest

from swarmline.mcp._session import StatefulSession
from swarmline.mcp._tools_team import (
    team_claim_task,
    team_create_task,
    team_list_agents,
    team_list_tasks,
    team_register_agent,
)


@pytest.fixture()
def session() -> StatefulSession:
    return StatefulSession(mode="headless")


class TestTeamRegisterAgent:
    """Tests for team_register_agent."""

    @pytest.mark.asyncio
    async def test_register_agent_success_returns_ok(
        self, session: StatefulSession
    ) -> None:
        result = await team_register_agent(session, id="a1", name="Alice", role="coder")
        assert result["ok"] is True
        assert result["data"]["agent_id"] == "a1"

    @pytest.mark.asyncio
    async def test_register_agent_duplicate_returns_error(
        self, session: StatefulSession
    ) -> None:
        await team_register_agent(session, id="a1", name="Alice", role="coder")
        result = await team_register_agent(
            session, id="a1", name="Alice2", role="coder"
        )
        assert result["ok"] is False
        assert "already registered" in result["error"]

    @pytest.mark.asyncio
    async def test_register_agent_with_metadata(self, session: StatefulSession) -> None:
        result = await team_register_agent(
            session, id="a2", name="Bob", role="reviewer", metadata={"level": "senior"}
        )
        assert result["ok"] is True
        agents = await team_list_agents(session)
        found = [a for a in agents["data"] if a["id"] == "a2"]
        assert found[0]["metadata"] == {"level": "senior"}


class TestTeamListAgents:
    """Tests for team_list_agents."""

    @pytest.mark.asyncio
    async def test_list_agents_empty_returns_empty(
        self, session: StatefulSession
    ) -> None:
        result = await team_list_agents(session)
        assert result["ok"] is True
        assert result["data"] == []

    @pytest.mark.asyncio
    async def test_list_agents_returns_registered(
        self, session: StatefulSession
    ) -> None:
        await team_register_agent(session, id="a1", name="Alice", role="coder")
        await team_register_agent(session, id="a2", name="Bob", role="reviewer")
        result = await team_list_agents(session)
        assert result["ok"] is True
        assert len(result["data"]) == 2
        ids = {a["id"] for a in result["data"]}
        assert ids == {"a1", "a2"}

    @pytest.mark.asyncio
    async def test_list_agents_filter_by_role(self, session: StatefulSession) -> None:
        await team_register_agent(session, id="a1", name="Alice", role="coder")
        await team_register_agent(session, id="a2", name="Bob", role="reviewer")
        result = await team_list_agents(session, role="coder")
        assert result["ok"] is True
        assert len(result["data"]) == 1
        assert result["data"][0]["id"] == "a1"

    @pytest.mark.asyncio
    async def test_list_agents_filter_by_status(self, session: StatefulSession) -> None:
        await team_register_agent(session, id="a1", name="Alice", role="coder")
        result = await team_list_agents(session, status="idle")
        assert result["ok"] is True
        assert len(result["data"]) == 1
        assert result["data"][0]["status"] == "idle"


class TestTeamCreateTask:
    """Tests for team_create_task."""

    @pytest.mark.asyncio
    async def test_create_task_success(self, session: StatefulSession) -> None:
        result = await team_create_task(session, id="t1", title="Fix bug")
        assert result["ok"] is True
        assert result["data"]["task_id"] == "t1"

    @pytest.mark.asyncio
    async def test_create_task_appears_in_list(self, session: StatefulSession) -> None:
        await team_create_task(session, id="t1", title="Fix bug", priority="HIGH")
        result = await team_list_tasks(session)
        assert result["ok"] is True
        assert len(result["data"]) == 1
        assert result["data"][0]["title"] == "Fix bug"
        assert result["data"][0]["priority"] == "high"


class TestTeamClaimTask:
    """Tests for team_claim_task."""

    @pytest.mark.asyncio
    async def test_claim_task_no_tasks_returns_error(
        self, session: StatefulSession
    ) -> None:
        result = await team_claim_task(session)
        assert result["ok"] is False
        assert "No tasks available" in result["error"]

    @pytest.mark.asyncio
    async def test_claim_task_gets_highest_priority(
        self, session: StatefulSession
    ) -> None:
        await team_create_task(session, id="t1", title="Low task", priority="LOW")
        await team_create_task(session, id="t2", title="High task", priority="HIGH")
        result = await team_claim_task(session)
        assert result["ok"] is True
        assert result["data"]["task_id"] == "t2"
        assert result["data"]["title"] == "High task"

    @pytest.mark.asyncio
    async def test_claim_task_assigned_to_agent(self, session: StatefulSession) -> None:
        await team_register_agent(session, id="a1", name="Alice", role="coder")
        await team_create_task(
            session, id="t1", title="Assigned task", assignee_agent_id="a1"
        )
        # Claim without assignee filter should not get assigned task
        result_unassigned = await team_claim_task(session)
        assert result_unassigned["ok"] is False

        # Claim with correct assignee should work
        result_assigned = await team_claim_task(session, assignee_agent_id="a1")
        assert result_assigned["ok"] is True
        assert result_assigned["data"]["task_id"] == "t1"

    @pytest.mark.asyncio
    async def test_claim_task_transitions_to_in_progress(
        self, session: StatefulSession
    ) -> None:
        await team_create_task(session, id="t1", title="Work item")
        await team_claim_task(session)
        tasks = await team_list_tasks(session, status="in_progress")
        assert tasks["ok"] is True
        assert len(tasks["data"]) == 1
        assert tasks["data"][0]["id"] == "t1"


class TestTeamListTasks:
    """Tests for team_list_tasks."""

    @pytest.mark.asyncio
    async def test_list_tasks_empty(self, session: StatefulSession) -> None:
        result = await team_list_tasks(session)
        assert result["ok"] is True
        assert result["data"] == []

    @pytest.mark.asyncio
    async def test_list_tasks_filter_by_status(self, session: StatefulSession) -> None:
        await team_create_task(session, id="t1", title="Task 1")
        await team_create_task(session, id="t2", title="Task 2")
        # Claim one to change its status
        await team_claim_task(session)
        todo = await team_list_tasks(session, status="todo")
        assert todo["ok"] is True
        assert len(todo["data"]) == 1

    @pytest.mark.asyncio
    async def test_list_tasks_filter_by_priority(
        self, session: StatefulSession
    ) -> None:
        await team_create_task(session, id="t1", title="Low", priority="LOW")
        await team_create_task(session, id="t2", title="High", priority="HIGH")
        result = await team_list_tasks(session, priority="HIGH")
        assert result["ok"] is True
        assert len(result["data"]) == 1
        assert result["data"][0]["id"] == "t2"

    @pytest.mark.asyncio
    async def test_list_tasks_filter_by_assignee(
        self, session: StatefulSession
    ) -> None:
        await team_create_task(session, id="t1", title="Unassigned")
        await team_create_task(
            session, id="t2", title="Assigned", assignee_agent_id="a1"
        )
        result = await team_list_tasks(session, assignee_agent_id="a1")
        assert result["ok"] is True
        assert len(result["data"]) == 1
        assert result["data"][0]["id"] == "t2"
