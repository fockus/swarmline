"""Тесты team types и protocol — TDD."""

from __future__ import annotations

from datetime import datetime, timezone


class TestTeamConfig:
    def test_create(self) -> None:
        from cognitia.orchestration.subagent_types import SubagentSpec
        from cognitia.orchestration.team_types import TeamConfig

        config = TeamConfig(
            lead_prompt="Ты тимлид",
            worker_specs=[SubagentSpec(name="w1", system_prompt="worker")],
        )
        assert config.max_workers == 4
        assert config.communication == "message_passing"


class TestTeamMessage:
    def test_create(self) -> None:
        from cognitia.orchestration.team_types import TeamMessage

        msg = TeamMessage(
            from_agent="lead", to_agent="w1",
            content="начинай задачу",
            timestamp=datetime.now(tz=timezone.utc),
        )
        assert msg.from_agent == "lead"


class TestTeamStatus:
    def test_default(self) -> None:
        from cognitia.orchestration.team_types import TeamStatus

        s = TeamStatus(team_id="t1")
        assert s.state == "idle"
        assert s.workers == {}
        assert s.messages_exchanged == 0


class TestTeamOrchestratorProtocol:
    def test_runtime_checkable(self) -> None:
        from cognitia.orchestration.team_protocol import TeamOrchestrator

        class FakeTeam:
            async def start(self, config, task):
                return "id"

            async def stop(self, team_id):
                pass

            async def get_team_status(self, team_id):
                return None

            async def send_message(self, team_id, message):
                pass

            async def pause_agent(self, team_id, agent_id):
                pass

        assert isinstance(FakeTeam(), TeamOrchestrator)

    def test_isp_max_5(self) -> None:
        from cognitia.orchestration.team_protocol import TeamOrchestrator

        methods = [n for n in dir(TeamOrchestrator) if not n.startswith("_") and callable(getattr(TeamOrchestrator, n, None))]
        assert len(methods) <= 5
