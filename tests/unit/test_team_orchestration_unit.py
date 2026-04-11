"""Tests DeepAgentsTeamOrchestrator, ClaudeTeamOrchestrator, TeamManager - TDD."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock
from unittest.mock import AsyncMock

import pytest
from swarmline.orchestration.subagent_types import SubagentSpec, SubagentStatus
from swarmline.orchestration.team_types import TeamConfig, TeamMessage


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
        from swarmline.orchestration.deepagents_team import DeepAgentsTeamOrchestrator

        orch = DeepAgentsTeamOrchestrator(mock_sub_orch)
        team_id = await orch.start(_config(), "задача")
        assert isinstance(team_id, str)
        assert mock_sub_orch.spawn.call_count == 2  # 2 workers

    async def test_stop(self, mock_sub_orch) -> None:
        from swarmline.orchestration.deepagents_team import DeepAgentsTeamOrchestrator

        orch = DeepAgentsTeamOrchestrator(mock_sub_orch)
        team_id = await orch.start(_config(), "t")
        await orch.stop(team_id)
        assert mock_sub_orch.cancel.call_count == 2

    async def test_get_status(self, mock_sub_orch) -> None:
        from swarmline.orchestration.deepagents_team import DeepAgentsTeamOrchestrator

        orch = DeepAgentsTeamOrchestrator(mock_sub_orch)
        team_id = await orch.start(_config(), "t")
        status = await orch.get_team_status(team_id)
        assert status.state == "completed"
        assert len(status.workers) == 2

    async def test_get_status_all_terminal_failures_returns_failed(self, mock_sub_orch) -> None:
        from swarmline.orchestration.deepagents_team import DeepAgentsTeamOrchestrator

        mock_sub_orch.get_status.side_effect = [
            SubagentStatus(state="failed"),
            SubagentStatus(state="cancelled"),
        ]
        orch = DeepAgentsTeamOrchestrator(mock_sub_orch)
        team_id = await orch.start(_config(), "t")

        status = await orch.get_team_status(team_id)

        assert status.state == "failed"
        assert status.workers["w1"].state == "failed"
        assert status.workers["w2"].state == "cancelled"

    async def test_send_message(self, mock_sub_orch) -> None:
        from swarmline.orchestration.deepagents_team import DeepAgentsTeamOrchestrator

        orch = DeepAgentsTeamOrchestrator(mock_sub_orch)
        team_id = await orch.start(_config(), "t")
        msg = TeamMessage(
            from_agent="lead", to_agent="w1", content="go", timestamp=datetime.now(tz=UTC)
        )
        await orch.send_message(team_id, msg)
        status = await orch.get_team_status(team_id)
        assert status.messages_exchanged == 1

    async def test_pause_and_resume_respawn_worker(self, mock_sub_orch) -> None:
        from swarmline.orchestration.deepagents_team import DeepAgentsTeamOrchestrator

        orch = DeepAgentsTeamOrchestrator(mock_sub_orch)
        team_id = await orch.start(_config(), "t")
        assert orch._teams[team_id].worker_ids["w1"] == "a1"

        await orch.pause_agent(team_id, "a1")
        await orch.resume_agent(team_id, "a1")

        assert orch._teams[team_id].worker_ids["w1"] == "a3"

    async def test_start_composes_worker_tasks_and_advertises_send_message(
        self,
        mock_sub_orch,
    ) -> None:
        from swarmline.orchestration.deepagents_team import DeepAgentsTeamOrchestrator

        mock_sub_orch.register_tool = MagicMock()
        orch = DeepAgentsTeamOrchestrator(mock_sub_orch)

        await orch.start(_config(), "investigate issue")

        first_spec, first_task = mock_sub_orch.spawn.await_args_list[0].args
        second_spec, second_task = mock_sub_orch.spawn.await_args_list[1].args

        assert "send_message" in [tool.name for tool in first_spec.tools]
        assert "send_message" in [tool.name for tool in second_spec.tools]
        assert "lead" in first_task
        assert "worker 'w1'" in first_task
        assert "investigate issue" in first_task
        assert "worker 'w2'" in second_task
        mock_sub_orch.register_tool.assert_called_once()

    async def test_resume_agent_reuses_composed_worker_task(self, mock_sub_orch) -> None:
        from swarmline.orchestration.deepagents_team import DeepAgentsTeamOrchestrator

        mock_sub_orch.register_tool = MagicMock()
        orch = DeepAgentsTeamOrchestrator(mock_sub_orch)
        team_id = await orch.start(_config(), "investigate issue")

        await orch.pause_agent(team_id, "a1")
        await orch.resume_agent(team_id, "a1")

        resumed_spec, resumed_task = mock_sub_orch.spawn.await_args_list[-1].args
        assert resumed_spec.name == "w1"
        assert "lead" in resumed_task
        assert "worker 'w1'" in resumed_task
        assert "investigate issue" in resumed_task

    async def test_isinstance_protocol(self, mock_sub_orch) -> None:
        from swarmline.orchestration.deepagents_team import DeepAgentsTeamOrchestrator
        from swarmline.orchestration.team_protocol import (
            ResumableTeamOrchestrator,
            TeamOrchestrator,
        )

        orch = DeepAgentsTeamOrchestrator(mock_sub_orch)
        assert isinstance(orch, TeamOrchestrator)
        assert isinstance(orch, ResumableTeamOrchestrator)


class TestClaudeTeamOrchestrator:
    async def test_start(self, mock_sub_orch) -> None:
        from swarmline.orchestration.claude_team import ClaudeTeamOrchestrator

        orch = ClaudeTeamOrchestrator(mock_sub_orch)
        team_id = await orch.start(_config(), "t")
        assert isinstance(team_id, str)
        first_worker_task = mock_sub_orch.spawn.await_args_list[0].args[1]
        assert "lead" in first_worker_task
        assert "worker 'w1'" in first_worker_task

    async def test_isinstance_protocol(self, mock_sub_orch) -> None:
        from swarmline.orchestration.claude_team import ClaudeTeamOrchestrator
        from swarmline.orchestration.team_protocol import TeamOrchestrator

        orch = ClaudeTeamOrchestrator(mock_sub_orch)
        assert isinstance(orch, TeamOrchestrator)


class TestTeamManager:
    async def test_start_and_list(self, mock_sub_orch) -> None:
        from swarmline.orchestration.deepagents_team import DeepAgentsTeamOrchestrator
        from swarmline.orchestration.team_manager import TeamManager

        orch = DeepAgentsTeamOrchestrator(mock_sub_orch)
        mgr = TeamManager(orch)

        team_id = await mgr.start_team(_config(), "task")
        teams = await mgr.list_teams()
        assert team_id in teams

    async def test_stop_removes_from_list(self, mock_sub_orch) -> None:
        from swarmline.orchestration.deepagents_team import DeepAgentsTeamOrchestrator
        from swarmline.orchestration.team_manager import TeamManager

        orch = DeepAgentsTeamOrchestrator(mock_sub_orch)
        mgr = TeamManager(orch)

        team_id = await mgr.start_team(_config(), "task")
        await mgr.stop_team(team_id)
        teams = await mgr.list_teams()
        assert team_id not in teams

    async def test_get_status(self, mock_sub_orch) -> None:
        from swarmline.orchestration.deepagents_team import DeepAgentsTeamOrchestrator
        from swarmline.orchestration.team_manager import TeamManager

        orch = DeepAgentsTeamOrchestrator(mock_sub_orch)
        mgr = TeamManager(orch)

        team_id = await mgr.start_team(_config(), "task")
        status = await mgr.get_status(team_id)
        assert status.team_id == team_id

    async def test_resume_agent_delegates_to_orchestrator(self, mock_sub_orch) -> None:
        from swarmline.orchestration.deepagents_team import DeepAgentsTeamOrchestrator
        from swarmline.orchestration.team_manager import TeamManager

        orch = DeepAgentsTeamOrchestrator(mock_sub_orch)
        mgr = TeamManager(orch)
        team_id = await mgr.start_team(_config(), "task")

        await mgr.pause_agent(team_id, "a1")
        await mgr.resume_agent(team_id, "a1")

        assert orch._teams[team_id].worker_ids["w1"] == "a3"

    async def test_resume_agent_noop_for_non_resumable_orchestrator(self) -> None:
        from swarmline.orchestration.team_manager import TeamManager

        class NonResumableOrchestrator:
            async def start(self, config, task):
                _ = (config, task)
                return "team-1"

            async def stop(self, team_id):
                _ = team_id

            async def get_team_status(self, team_id):
                from swarmline.orchestration.team_types import TeamStatus

                return TeamStatus(team_id=team_id)

            async def send_message(self, team_id, message):
                _ = (team_id, message)

            async def pause_agent(self, team_id, agent_id):
                _ = (team_id, agent_id)

        mgr = TeamManager(NonResumableOrchestrator())  # type: ignore[arg-type]
        await mgr.resume_agent("team-1", "agent-1")
