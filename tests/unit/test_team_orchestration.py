"""Тесты DeepAgentsTeamOrchestrator, ClaudeTeamOrchestrator, TeamManager — TDD."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from cognitia.orchestration.subagent_types import SubagentSpec, SubagentStatus
from cognitia.orchestration.team_types import TeamConfig, TeamMessage


def _config() -> TeamConfig:
    return TeamConfig(
        lead_prompt="lead",
        worker_specs=[
            SubagentSpec(name="w1", system_prompt="worker 1"),
            SubagentSpec(name="w2", system_prompt="worker 2"),
        ],
    )


@pytest.fixture()
def mock_sub_orch() -> AsyncMock:
    orch = AsyncMock()
    orch.spawn.side_effect = ["a1", "a2", "a3"]
    orch.get_status.return_value = SubagentStatus(state="completed")
    return orch


class TestDeepAgentsTeamOrchestrator:
    async def test_start(self, mock_sub_orch) -> None:
        from cognitia.orchestration.deepagents_team import DeepAgentsTeamOrchestrator

        orch = DeepAgentsTeamOrchestrator(mock_sub_orch)
        team_id = await orch.start(_config(), "задача")
        assert isinstance(team_id, str)
        assert mock_sub_orch.spawn.call_count == 2  # 2 workers

    async def test_stop(self, mock_sub_orch) -> None:
        from cognitia.orchestration.deepagents_team import DeepAgentsTeamOrchestrator

        orch = DeepAgentsTeamOrchestrator(mock_sub_orch)
        team_id = await orch.start(_config(), "t")
        await orch.stop(team_id)
        assert mock_sub_orch.cancel.call_count == 2

    async def test_get_status(self, mock_sub_orch) -> None:
        from cognitia.orchestration.deepagents_team import DeepAgentsTeamOrchestrator

        orch = DeepAgentsTeamOrchestrator(mock_sub_orch)
        team_id = await orch.start(_config(), "t")
        status = await orch.get_team_status(team_id)
        assert status.state == "completed"
        assert len(status.workers) == 2

    async def test_send_message(self, mock_sub_orch) -> None:
        from cognitia.orchestration.deepagents_team import DeepAgentsTeamOrchestrator

        orch = DeepAgentsTeamOrchestrator(mock_sub_orch)
        team_id = await orch.start(_config(), "t")
        msg = TeamMessage(from_agent="lead", to_agent="w1", content="go", timestamp=datetime.now(tz=timezone.utc))
        await orch.send_message(team_id, msg)
        status = await orch.get_team_status(team_id)
        assert status.messages_exchanged == 1

    async def test_pause_and_resume_respawn_worker(self, mock_sub_orch) -> None:
        from cognitia.orchestration.deepagents_team import DeepAgentsTeamOrchestrator

        orch = DeepAgentsTeamOrchestrator(mock_sub_orch)
        team_id = await orch.start(_config(), "t")
        assert orch._teams[team_id].worker_ids["w1"] == "a1"

        await orch.pause_agent(team_id, "a1")
        await orch.resume_agent(team_id, "a1")

        assert orch._teams[team_id].worker_ids["w1"] == "a3"

    async def test_isinstance_protocol(self, mock_sub_orch) -> None:
        from cognitia.orchestration.deepagents_team import DeepAgentsTeamOrchestrator
        from cognitia.orchestration.team_protocol import TeamOrchestrator

        orch = DeepAgentsTeamOrchestrator(mock_sub_orch)
        assert isinstance(orch, TeamOrchestrator)


class TestClaudeTeamOrchestrator:
    async def test_start(self, mock_sub_orch) -> None:
        from cognitia.orchestration.claude_team import ClaudeTeamOrchestrator

        orch = ClaudeTeamOrchestrator(mock_sub_orch)
        team_id = await orch.start(_config(), "t")
        assert isinstance(team_id, str)

    async def test_isinstance_protocol(self, mock_sub_orch) -> None:
        from cognitia.orchestration.claude_team import ClaudeTeamOrchestrator
        from cognitia.orchestration.team_protocol import TeamOrchestrator

        orch = ClaudeTeamOrchestrator(mock_sub_orch)
        assert isinstance(orch, TeamOrchestrator)


class TestTeamManager:
    async def test_start_and_list(self, mock_sub_orch) -> None:
        from cognitia.orchestration.deepagents_team import DeepAgentsTeamOrchestrator
        from cognitia.orchestration.team_manager import TeamManager

        orch = DeepAgentsTeamOrchestrator(mock_sub_orch)
        mgr = TeamManager(orch)

        team_id = await mgr.start_team(_config(), "task")
        teams = await mgr.list_teams()
        assert team_id in teams

    async def test_stop_removes_from_list(self, mock_sub_orch) -> None:
        from cognitia.orchestration.deepagents_team import DeepAgentsTeamOrchestrator
        from cognitia.orchestration.team_manager import TeamManager

        orch = DeepAgentsTeamOrchestrator(mock_sub_orch)
        mgr = TeamManager(orch)

        team_id = await mgr.start_team(_config(), "task")
        await mgr.stop_team(team_id)
        teams = await mgr.list_teams()
        assert team_id not in teams

    async def test_get_status(self, mock_sub_orch) -> None:
        from cognitia.orchestration.deepagents_team import DeepAgentsTeamOrchestrator
        from cognitia.orchestration.team_manager import TeamManager

        orch = DeepAgentsTeamOrchestrator(mock_sub_orch)
        mgr = TeamManager(orch)

        team_id = await mgr.start_team(_config(), "task")
        status = await mgr.get_status(team_id)
        assert status.team_id == team_id

    async def test_resume_agent_delegates_to_orchestrator(self, mock_sub_orch) -> None:
        from cognitia.orchestration.deepagents_team import DeepAgentsTeamOrchestrator
        from cognitia.orchestration.team_manager import TeamManager

        orch = DeepAgentsTeamOrchestrator(mock_sub_orch)
        mgr = TeamManager(orch)
        team_id = await mgr.start_team(_config(), "task")

        await mgr.pause_agent(team_id, "a1")
        await mgr.resume_agent(team_id, "a1")

        assert orch._teams[team_id].worker_ids["w1"] == "a3"
