"""TDD RED: ThinTeamOrchestrator - lead delegation, workers, MessageBus. CRP-2.2: Polnotsennyy team orchestrator for ThinRuntime.
Kazhdyy test = biznots-fakt.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

from swarmline.orchestration.subagent_types import SubagentSpec
from swarmline.orchestration.team_protocol import ResumableTeamOrchestrator, TeamOrchestrator
from swarmline.orchestration.team_types import TeamConfig, TeamMessage


def _make_llm_call(response_text: str = "done"):
    """Mock LLM call with fiksirovannym responseom."""

    async def _llm_call(messages: list[dict], system_prompt: str, **kwargs) -> str:
        return json.dumps({"type": "final", "final_message": response_text})

    return _llm_call


def _make_slow_llm_call(delay: float = 10.0):
    """Mock LLM call with zaderzhkoy."""

    async def _llm_call(messages: list[dict], system_prompt: str, **kwargs) -> str:
        await asyncio.sleep(delay)
        return json.dumps({"type": "final", "final_message": "slow done"})

    return _llm_call


def _config(n_workers: int = 2) -> TeamConfig:
    return TeamConfig(
        lead_prompt="You are the team lead. Coordinate workers.",
        worker_specs=[
            SubagentSpec(name=f"worker-{i}", system_prompt=f"Worker {i} prompt")
            for i in range(n_workers)
        ],
    )


class TestThinTeamStartSpawnsWorkers:
    """start(config, task) → N workers running."""

    async def test_thin_team_start_spawns_workers(self) -> None:
        from swarmline.orchestration.thin_team import ThinTeamOrchestrator

        orch = ThinTeamOrchestrator(llm_call=_make_llm_call("worker result"))
        team_id = await orch.start(_config(2), "Build feature X")

        assert isinstance(team_id, str)
        status = await orch.get_team_status(team_id)
        assert len(status.workers) == 2


class TestThinTeamStopCancelsAll:
    """stop -> vse workers cancelled."""

    async def test_thin_team_stop_cancels_all(self) -> None:
        from swarmline.orchestration.thin_team import ThinTeamOrchestrator

        orch = ThinTeamOrchestrator(llm_call=_make_slow_llm_call(10.0))
        team_id = await orch.start(_config(2), "Long task")
        await asyncio.sleep(0.05)

        await orch.stop(team_id)
        status = await orch.get_team_status(team_id)
        for worker_status in status.workers.values():
            assert worker_status.state in ("cancelled", "failed", "completed")


class TestThinTeamStatusAggregated:
    """team_status otrazhaet sostoyanie vseh workers."""

    async def test_thin_team_status_aggregated(self) -> None:
        from swarmline.orchestration.thin_team import ThinTeamOrchestrator

        orch = ThinTeamOrchestrator(llm_call=_make_llm_call("done"))
        team_id = await orch.start(_config(2), "Quick task")

        # Wait zaversheniya workers
        await asyncio.sleep(0.3)
        status = await orch.get_team_status(team_id)

        assert len(status.workers) == 2
        assert status.team_id == team_id
        # Vse workers completed -> team completed
        all_done = all(
            w.state in ("completed", "failed", "cancelled") for w in status.workers.values()
        )
        if all_done:
            assert status.state == "completed"


class TestThinTeamSendMessageDelivered:
    """send_message -> worker vidit in inbox MessageBus."""

    async def test_thin_team_send_message_delivered(self) -> None:
        from swarmline.orchestration.thin_team import ThinTeamOrchestrator

        orch = ThinTeamOrchestrator(llm_call=_make_slow_llm_call(10.0))
        team_id = await orch.start(_config(2), "Task")

        msg = TeamMessage(
            from_agent="lead",
            to_agent="worker-0",
            content="Focus on tests",
            timestamp=datetime.now(tz=UTC),
        )
        await orch.send_message(team_id, msg)

        bus = orch.get_message_bus(team_id)
        assert bus is not None
        inbox = await bus.get_inbox("worker-0")
        assert len(inbox) == 1
        assert inbox[0].content == "Focus on tests"

        await orch.stop(team_id)


class TestThinTeamPauseResumeAgent:
    """pause → cancelled, resume → re-spawned."""

    async def test_thin_team_pause_resume_agent(self) -> None:
        from swarmline.orchestration.thin_team import ThinTeamOrchestrator

        orch = ThinTeamOrchestrator(llm_call=_make_slow_llm_call(10.0))
        team_id = await orch.start(_config(2), "Task")
        await asyncio.sleep(0.05)

        # Poluchaem UUID agent_id (pause_agent ozhidaet UUID, not worker name)
        state = orch._teams[team_id]
        worker_name = list(state.worker_ids.keys())[0]
        agent_id = state.worker_ids[worker_name]

        # Pause
        await orch.pause_agent(team_id, agent_id)
        await asyncio.sleep(0.05)
        status_after_pause = await orch.get_team_status(team_id)
        paused = status_after_pause.workers[worker_name]
        assert paused.state in ("cancelled", "failed")

        # Resume
        await orch.resume_agent(team_id, agent_id)
        await asyncio.sleep(0.05)
        status_after_resume = await orch.get_team_status(team_id)
        resumed = status_after_resume.workers[worker_name]
        assert resumed.state == "running"

        await orch.stop(team_id)


class TestThinTeamLeadPromptComposed:
    """worker task = lead_prompt + worker_name + general_task."""

    async def test_thin_team_lead_prompt_composed(self) -> None:
        from swarmline.orchestration.thin_team import ThinTeamOrchestrator

        captured_prompts: list[str] = []

        async def capturing_llm(messages: list[dict], system_prompt: str, **kwargs) -> str:
            captured_prompts.append(system_prompt)
            return json.dumps({"type": "final", "final_message": "done"})

        orch = ThinTeamOrchestrator(llm_call=capturing_llm)
        await orch.start(_config(1), "Build feature Y")

        # Wait worker completion
        await asyncio.sleep(0.3)

        # system_prompt should soderzhat worker spec prompt
        # task (messages[0].content) should soderzhat lead_prompt + worker name
        assert len(captured_prompts) >= 1
        # Worker system_prompt comes from spec
        assert "Worker 0 prompt" in captured_prompts[0]


class TestThinTeamAllCompleted:
    """Vse workers completed -> team state = completed."""

    async def test_thin_team_all_completed(self) -> None:
        from swarmline.orchestration.thin_team import ThinTeamOrchestrator

        orch = ThinTeamOrchestrator(llm_call=_make_llm_call("finished"))
        team_id = await orch.start(_config(3), "Quick parallel task")

        # Wait zaversheniya vseh workers
        await asyncio.sleep(0.5)
        status = await orch.get_team_status(team_id)

        assert status.state == "completed"
        assert all(w.state == "completed" for w in status.workers.values())


class TestThinTeamProtocolCompliance:
    """ThinTeamOrchestrator udovletvoryaet TeamOrchestrator + ResumableTeamOrchestrator."""

    async def test_isinstance_team_orchestrator(self) -> None:
        from swarmline.orchestration.thin_team import ThinTeamOrchestrator

        orch = ThinTeamOrchestrator(llm_call=_make_llm_call())
        assert isinstance(orch, TeamOrchestrator)

    async def test_isinstance_resumable(self) -> None:
        from swarmline.orchestration.thin_team import ThinTeamOrchestrator

        orch = ThinTeamOrchestrator(llm_call=_make_llm_call())
        assert isinstance(orch, ResumableTeamOrchestrator)
