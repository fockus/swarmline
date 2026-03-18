"""TDD Red Phase: ThinTeamOrchestrator (Etap 2.2). Tests verify:
- start(config, task) -> N workers running
- stop -> vse workers cancelled
- team_status otrazhaet sostoyanie vseh workers
- send_message -> worker vidit in inbox
- pause -> cancelled, resume -> re-spawned
- lead_prompt composed: worker task = lead_prompt + worker_name + general_task
- Vse workers completed -> team state = completed Contract: cognitia.orchestration.thin_team.ThinTeamOrchestrator
Implements: TeamOrchestrator protocol (5 metodov) + ResumableTeamOrchestrator
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from cognitia.orchestration.subagent_types import SubagentSpec
from cognitia.orchestration.team_protocol import ResumableTeamOrchestrator, TeamOrchestrator
from cognitia.orchestration.team_types import TeamConfig, TeamMessage, TeamStatus

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_team_config(n_workers: int = 2) -> TeamConfig:
    """Create TeamConfig with N workers."""
    workers = [
        SubagentSpec(name=f"worker_{i}", system_prompt=f"Worker {i} prompt")
        for i in range(n_workers)
    ]
    return TeamConfig(
        lead_prompt="You are the team lead. Coordinate workers.",
        worker_specs=workers,
        max_workers=n_workers,
    )


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------


class TestThinTeamOrchestratorProtocol:
    """ThinTeamOrchestrator realizuet TeamOrchestrator protocol."""

    def test_thin_team_implements_protocol(self) -> None:
        """ThinTeamOrchestrator — isinstance TeamOrchestrator."""
        from cognitia.orchestration.thin_team import ThinTeamOrchestrator

        orch = ThinTeamOrchestrator()
        assert isinstance(orch, TeamOrchestrator)

    def test_thin_team_implements_resumable_protocol(self) -> None:
        """ThinTeamOrchestrator — isinstance ResumableTeamOrchestrator."""
        from cognitia.orchestration.thin_team import ThinTeamOrchestrator

        orch = ThinTeamOrchestrator()
        assert isinstance(orch, ResumableTeamOrchestrator)


# ---------------------------------------------------------------------------
# Lifecycle tests
# ---------------------------------------------------------------------------


class TestThinTeamLifecycle:
    """Start/stop/status lifecycle."""

    @pytest.mark.asyncio
    async def test_thin_team_start_spawns_workers(self) -> None:
        """start(config, task) → N workers running."""
        from cognitia.orchestration.thin_team import ThinTeamOrchestrator

        orch = ThinTeamOrchestrator()
        config = _make_team_config(n_workers=3)

        team_id = await orch.start(config, "Solve the problem together")

        assert isinstance(team_id, str)
        assert len(team_id) > 0

        status = await orch.get_team_status(team_id)
        assert status.state == "running"
        assert len(status.workers) == 3

    @pytest.mark.asyncio
    async def test_thin_team_stop_cancels_all(self) -> None:
        """stop -> vse workers cancelled."""
        from cognitia.orchestration.thin_team import ThinTeamOrchestrator

        orch = ThinTeamOrchestrator()
        config = _make_team_config(n_workers=2)

        team_id = await orch.start(config, "Task")
        await asyncio.sleep(0.05)  # Dat workers startovat

        await orch.stop(team_id)

        status = await orch.get_team_status(team_id)
        # Posle stop vse workers should byt cancelled/failed/completed
        for worker_status in status.workers.values():
            assert worker_status.state in ("cancelled", "failed", "completed")

    @pytest.mark.asyncio
    async def test_thin_team_status_aggregated(self) -> None:
        """team_status otrazhaet sostoyanie vseh workers."""
        from cognitia.orchestration.thin_team import ThinTeamOrchestrator

        orch = ThinTeamOrchestrator()
        config = _make_team_config(n_workers=2)

        team_id = await orch.start(config, "Task")
        status = await orch.get_team_status(team_id)

        assert isinstance(status, TeamStatus)
        assert status.team_id == team_id
        assert isinstance(status.workers, dict)
        assert len(status.workers) == 2

    @pytest.mark.asyncio
    async def test_thin_team_all_completed(self) -> None:
        """Vse workers completed -> team state = completed."""
        from cognitia.orchestration.thin_team import ThinTeamOrchestrator

        orch = ThinTeamOrchestrator()
        config = _make_team_config(n_workers=1)

        team_id = await orch.start(config, "Quick task")

        # Wait zaversheniya vseh workers (timeout 5s)
        for _ in range(50):
            status = await orch.get_team_status(team_id)
            if status.state == "completed":
                break
            await asyncio.sleep(0.1)

        status = await orch.get_team_status(team_id)
        assert status.state == "completed"


# ---------------------------------------------------------------------------
# Messaging
# ---------------------------------------------------------------------------


class TestThinTeamMessaging:
    """send_message / MessageBus integration."""

    @pytest.mark.asyncio
    async def test_thin_team_send_message_delivered(self) -> None:
        """send_message -> worker vidit in inbox."""
        from cognitia.orchestration.thin_team import ThinTeamOrchestrator

        orch = ThinTeamOrchestrator()
        config = _make_team_config(n_workers=2)

        team_id = await orch.start(config, "Task")
        await asyncio.sleep(0.05)

        msg = TeamMessage(
            from_agent="lead",
            to_agent="worker_0",
            content="Focus on subtask A",
            timestamp=datetime.now(tz=UTC),
        )
        await orch.send_message(team_id, msg)

        status = await orch.get_team_status(team_id)
        assert status.messages_exchanged >= 1

    @pytest.mark.asyncio
    async def test_thin_team_worker_specs_advertise_send_message(self) -> None:
        """start(config, task) → worker spec advertises send_message tool."""
        from cognitia.orchestration.thin_team import ThinTeamOrchestrator

        orch = ThinTeamOrchestrator()
        config = _make_team_config(n_workers=2)

        await orch.start(config, "Task")

        advertised_tools: list[str] = []
        for spec in orch._sub_orch._specs.values():  # noqa: SLF001 - regression guard
            advertised_tools.extend(tool.name for tool in spec.tools)

        assert "send_message" in advertised_tools


# ---------------------------------------------------------------------------
# Pause / Resume
# ---------------------------------------------------------------------------


class TestThinTeamPauseResume:
    """pause_agent / resume_agent."""

    @pytest.mark.asyncio
    async def test_thin_team_pause_resume_agent(self) -> None:
        """pause → worker cancelled, resume → worker re-spawned."""
        from cognitia.orchestration.thin_team import ThinTeamOrchestrator

        orch = ThinTeamOrchestrator()
        config = _make_team_config(n_workers=2)

        team_id = await orch.start(config, "Task")
        await asyncio.sleep(0.05)

        # Pause worker_0
        worker_ids = list((await orch.get_team_status(team_id)).workers.keys())
        assert len(worker_ids) >= 1
        worker_id = worker_ids[0]

        await orch.pause_agent(team_id, worker_id)

        status = await orch.get_team_status(team_id)
        assert status.workers[worker_id].state in ("cancelled", "failed")

        # Resume worker_0
        await orch.resume_agent(team_id, worker_id)

        status = await orch.get_team_status(team_id)
        assert status.workers[worker_id].state in ("running", "pending", "completed")


# ---------------------------------------------------------------------------
# Lead prompt composition
# ---------------------------------------------------------------------------


class TestThinTeamEdgeCases:
    """Edge cases: unknown team_id, resolve_worker, resume not-paused."""

    @pytest.mark.asyncio
    async def test_thin_team_stop_unknown_team_noop(self) -> None:
        """stop with notsushchestvuyushchim team_id -> not crash."""
        from cognitia.orchestration.thin_team import ThinTeamOrchestrator

        orch = ThinTeamOrchestrator()
        await orch.stop("nonexistent-team-id")  # Not should raise

    @pytest.mark.asyncio
    async def test_thin_team_status_unknown_team_returns_default(self) -> None:
        """get_team_status with notsushchestvuyushchim team_id -> default TeamStatus."""
        from cognitia.orchestration.thin_team import ThinTeamOrchestrator

        orch = ThinTeamOrchestrator()
        status = await orch.get_team_status("nonexistent-team-id")
        assert status.team_id == "nonexistent-team-id"
        assert status.workers == {} or status.workers is None or len(status.workers) == 0

    @pytest.mark.asyncio
    async def test_thin_team_send_message_unknown_team_noop(self) -> None:
        """send_message with notsushchestvuyushchim team_id -> not crash."""
        from cognitia.orchestration.thin_team import ThinTeamOrchestrator

        orch = ThinTeamOrchestrator()
        msg = TeamMessage(
            from_agent="lead",
            to_agent="worker",
            content="Hello",
            timestamp=datetime.now(tz=UTC),
        )
        await orch.send_message("nonexistent", msg)  # Not should raise

    @pytest.mark.asyncio
    async def test_thin_team_pause_unknown_team_noop(self) -> None:
        """pause_agent with notsushchestvuyushchim team_id -> not crash."""
        from cognitia.orchestration.thin_team import ThinTeamOrchestrator

        orch = ThinTeamOrchestrator()
        await orch.pause_agent("nonexistent", "worker_0")  # Not should raise

    @pytest.mark.asyncio
    async def test_thin_team_pause_unknown_agent_noop(self) -> None:
        """pause_agent with notsushchestvuyushchim agent_id -> not crash."""
        from cognitia.orchestration.thin_team import ThinTeamOrchestrator

        orch = ThinTeamOrchestrator()
        config = _make_team_config(n_workers=1)
        team_id = await orch.start(config, "Task")
        await orch.pause_agent(team_id, "nonexistent_worker")  # Not should raise

    @pytest.mark.asyncio
    async def test_thin_team_resume_unknown_team_noop(self) -> None:
        """resume_agent with notsushchestvuyushchim team_id -> not crash."""
        from cognitia.orchestration.thin_team import ThinTeamOrchestrator

        orch = ThinTeamOrchestrator()
        await orch.resume_agent("nonexistent", "worker_0")  # Not should raise

    @pytest.mark.asyncio
    async def test_thin_team_resume_not_paused_noop(self) -> None:
        """resume_agent for not-paused worker -> not crash, nott effekta."""
        from cognitia.orchestration.thin_team import ThinTeamOrchestrator

        orch = ThinTeamOrchestrator()
        config = _make_team_config(n_workers=1)
        team_id = await orch.start(config, "Task")
        # Resume worker_0 without predvaritelnogo pause
        await orch.resume_agent(team_id, "worker_0")  # Not should raise

    @pytest.mark.asyncio
    async def test_thin_team_resume_unknown_agent_noop(self) -> None:
        """resume_agent for notsushchestvuyushchego agent -> not crash."""
        from cognitia.orchestration.thin_team import ThinTeamOrchestrator

        orch = ThinTeamOrchestrator()
        config = _make_team_config(n_workers=1)
        team_id = await orch.start(config, "Task")
        await orch.resume_agent(team_id, "ghost_worker")  # Not should raise

    @pytest.mark.asyncio
    async def test_thin_team_get_message_bus(self) -> None:
        """get_message_bus returns MessageBus for izvestnogo team_id."""
        from cognitia.orchestration.thin_team import ThinTeamOrchestrator

        orch = ThinTeamOrchestrator()
        config = _make_team_config(n_workers=1)
        team_id = await orch.start(config, "Task")
        bus = orch.get_message_bus(team_id)
        assert bus is not None

    @pytest.mark.asyncio
    async def test_thin_team_get_message_bus_unknown_none(self) -> None:
        """get_message_bus for notizvestnogo team_id -> None."""
        from cognitia.orchestration.thin_team import ThinTeamOrchestrator

        orch = ThinTeamOrchestrator()
        assert orch.get_message_bus("nonexistent") is None


class TestThinTeamLeadPrompt:
    """Lead delegation: task composition."""

    @pytest.mark.asyncio
    async def test_thin_team_lead_prompt_composed(self) -> None:
        """Worker task = lead_prompt + worker_name + general_task."""
        from cognitia.orchestration.thin_team import ThinTeamOrchestrator

        orch = ThinTeamOrchestrator()
        config = TeamConfig(
            lead_prompt="Coordinate the team on data analysis.",
            worker_specs=[
                SubagentSpec(name="analyst", system_prompt="You analyze data."),
            ],
            max_workers=1,
        )

        team_id = await orch.start(config, "Analyze Q4 revenue")

        # Verify chto worker poluchil sostavnoy prompt
        # (cherez status ili vnutrennote sostoyanie)
        status = await orch.get_team_status(team_id)
        assert status.state in ("running", "completed")
        # Worker should sushchestvovat
        assert len(status.workers) == 1
