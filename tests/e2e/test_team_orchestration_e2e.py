"""E2E: Team orchestration — полный lifecycle multi-agent команды.

ThinTeamOrchestrator + ThinSubagentOrchestrator с fake LLM.
Реальные компоненты: MessageBus, asyncio.Task workers, runtime.
Единственный mock: LLM callable (внешняя граница).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from cognitia.orchestration.message_bus import MessageBus
from cognitia.orchestration.subagent_types import SubagentSpec
from cognitia.orchestration.team_types import TeamConfig
from cognitia.orchestration.thin_subagent import ThinSubagentOrchestrator
from cognitia.orchestration.thin_team import ThinTeamOrchestrator
from cognitia.runtime.types import RuntimeConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _final_envelope(text: str) -> str:
    """Сформировать JSON-ответ LLM в формате final envelope."""
    return json.dumps({"type": "final", "final_message": text})


def _make_worker_spec(name: str, prompt: str = "You are a worker") -> SubagentSpec:
    """Создать SubagentSpec для worker'а."""
    return SubagentSpec(name=name, system_prompt=prompt, tools=[])


# ---------------------------------------------------------------------------
# 1. Team full lifecycle: start to complete
# ---------------------------------------------------------------------------


class TestTeamFullLifecycleE2E:
    """Team: start -> workers execute -> all complete."""

    @pytest.mark.asyncio
    async def test_team_full_lifecycle_start_to_complete(self) -> None:
        """ThinTeamOrchestrator -> start(config with 2 workers) -> оба complete.

        Workers выполняются через fake LLM, каждый получает свой task.
        """
        worker_tasks_received: list[str] = []

        async def fake_llm(
            messages: list[dict[str, str]], system_prompt: str, **kwargs: Any
        ) -> str:
            # Запоминаем полученные задания
            user_msg = next((m["content"] for m in messages if m["role"] == "user"), "")
            worker_tasks_received.append(user_msg[:50])
            await asyncio.sleep(0.05)
            return _final_envelope(f"done by worker")

        config = TeamConfig(
            lead_prompt="You are the team lead. Coordinate the work.",
            worker_specs=[
                _make_worker_spec("researcher", "Research the topic"),
                _make_worker_spec("writer", "Write the document"),
            ],
            max_workers=4,
        )

        orchestrator = ThinTeamOrchestrator(
            llm_call=fake_llm,
            runtime_config=RuntimeConfig(runtime_name="thin"),
        )

        team_id = await orchestrator.start(config, task="Analyze AI trends")

        # Ждём завершения workers
        for _ in range(50):
            status = await orchestrator.get_team_status(team_id)
            if status.state == "completed":
                break
            await asyncio.sleep(0.1)

        status = await orchestrator.get_team_status(team_id)
        assert status.state == "completed", f"Team должна завершиться, но state={status.state}"
        assert len(status.workers) == 2, "Должно быть 2 worker'а"
        assert all(
            w.state == "completed" for w in status.workers.values()
        ), "Все workers должны завершиться"


# ---------------------------------------------------------------------------
# 2. Message bus — worker communication
# ---------------------------------------------------------------------------


class TestTeamMessageBusE2E:
    """MessageBus: workers обмениваются сообщениями."""

    @pytest.mark.asyncio
    async def test_team_message_bus_worker_communication(self) -> None:
        """Team с 2 workers, сообщения через MessageBus видны в истории.

        Проверяем bus.send() + bus.get_history() через прямой доступ к bus.
        """
        bus = MessageBus()

        from cognitia.orchestration.team_types import TeamMessage
        from datetime import UTC, datetime

        # Worker 1 отправляет сообщение worker 2
        await bus.send(
            TeamMessage(
                from_agent="researcher",
                to_agent="writer",
                content="I found key insights about AI trends",
                timestamp=datetime.now(tz=UTC),
            )
        )

        # Worker 2 отвечает
        await bus.send(
            TeamMessage(
                from_agent="writer",
                to_agent="researcher",
                content="Thanks, integrating into the summary",
                timestamp=datetime.now(tz=UTC),
            )
        )

        history = await bus.get_history()
        assert len(history) == 2, "Bus должен содержать 2 сообщения"
        assert history[0].from_agent == "researcher"
        assert history[0].to_agent == "writer"
        assert "AI trends" in history[0].content
        assert history[1].from_agent == "writer"

        # Inbox filtering
        writer_inbox = await bus.get_inbox("writer")
        assert len(writer_inbox) == 1
        assert writer_inbox[0].from_agent == "researcher"

        researcher_inbox = await bus.get_inbox("researcher")
        assert len(researcher_inbox) == 1
        assert researcher_inbox[0].from_agent == "writer"

    @pytest.mark.asyncio
    async def test_team_broadcast_message(self) -> None:
        """Broadcast: одно сообщение доставляется всем recipients."""
        bus = MessageBus()
        await bus.broadcast(
            from_agent="lead",
            content="Start working on the task",
            recipients=["worker_a", "worker_b", "worker_c"],
        )

        history = await bus.get_history()
        assert len(history) == 3, "Broadcast создаёт по сообщению на каждого recipient"

        for name in ["worker_a", "worker_b", "worker_c"]:
            inbox = await bus.get_inbox(name)
            assert len(inbox) == 1
            assert inbox[0].content == "Start working on the task"


# ---------------------------------------------------------------------------
# 3. Pause and resume worker
# ---------------------------------------------------------------------------


class TestTeamPauseResumeE2E:
    """Team: pause -> status = paused -> resume -> status = completed."""

    @pytest.mark.asyncio
    async def test_team_pause_resume_worker(self) -> None:
        """Start team -> pause worker -> status = paused -> resume -> completed.

        Resume создаёт новый spawn для worker'а.
        """
        call_count = 0

        async def fake_llm(
            messages: list[dict[str, str]], system_prompt: str, **kwargs: Any
        ) -> str:
            nonlocal call_count
            call_count += 1
            # Делаем задержку чтобы успеть pause
            await asyncio.sleep(0.3)
            return _final_envelope(f"done #{call_count}")

        config = TeamConfig(
            lead_prompt="Team lead",
            worker_specs=[
                _make_worker_spec("slow_worker"),
                _make_worker_spec("fast_worker"),
            ],
            max_workers=4,
        )

        orchestrator = ThinTeamOrchestrator(
            llm_call=fake_llm,
            runtime_config=RuntimeConfig(runtime_name="thin"),
        )

        team_id = await orchestrator.start(config, task="Do the work")

        # Даём workers начать выполнение
        await asyncio.sleep(0.05)

        # Pause slow_worker
        await orchestrator.pause_agent(team_id, "slow_worker")

        # Проверяем: slow_worker paused (cancelled)
        status = await orchestrator.get_team_status(team_id)
        slow_status = status.workers.get("slow_worker")
        assert slow_status is not None
        assert slow_status.state in ("cancelled", "failed"), (
            f"Paused worker должен быть cancelled, но state={slow_status.state}"
        )

        # Resume slow_worker — создаёт новый spawn
        await orchestrator.resume_agent(team_id, "slow_worker")

        # Ждём завершения обоих workers
        for _ in range(60):
            status = await orchestrator.get_team_status(team_id)
            if status.state == "completed":
                break
            await asyncio.sleep(0.1)

        status = await orchestrator.get_team_status(team_id)
        assert status.state == "completed", f"Team должна завершиться после resume, state={status.state}"


# ---------------------------------------------------------------------------
# 4. Subagent spawn → execute → collect
# ---------------------------------------------------------------------------


class TestSubagentSpawnE2E:
    """ThinSubagentOrchestrator: spawn -> execute -> collect results."""

    @pytest.mark.asyncio
    async def test_subagent_spawn_execute_collect(self) -> None:
        """Spawn 3 subagents parallel -> all complete -> collect results."""
        agent_outputs: dict[str, str] = {}

        async def fake_llm(
            messages: list[dict[str, str]], system_prompt: str, **kwargs: Any
        ) -> str:
            await asyncio.sleep(0.05)
            # Извлекаем имя из system_prompt для уникальности результата
            return _final_envelope(f"output from {system_prompt[:20]}")

        orchestrator = ThinSubagentOrchestrator(
            max_concurrent=4,
            llm_call=fake_llm,
            runtime_config=RuntimeConfig(runtime_name="thin"),
        )

        specs = [
            SubagentSpec(name="agent_a", system_prompt="Agent A does research"),
            SubagentSpec(name="agent_b", system_prompt="Agent B does analysis"),
            SubagentSpec(name="agent_c", system_prompt="Agent C does writing"),
        ]

        # Spawn 3 subagents
        agent_ids = []
        for spec in specs:
            aid = await orchestrator.spawn(spec, f"Task for {spec.name}")
            agent_ids.append(aid)

        assert len(agent_ids) == 3, "Должно быть 3 agent id"

        # Wait for all and collect
        results = []
        for aid in agent_ids:
            result = await orchestrator.wait(aid)
            results.append(result)

        assert len(results) == 3, "Должно быть 3 результата"
        for result in results:
            assert result.status.state == "completed", (
                f"Agent {result.agent_id} должен complete, но state={result.status.state}"
            )
            assert result.output, f"Agent {result.agent_id} должен вернуть output"

    @pytest.mark.asyncio
    async def test_subagent_max_concurrent_limit(self) -> None:
        """Spawn больше max_concurrent -> ValueError."""
        async def fake_llm(messages: list, system_prompt: str, **kwargs: Any) -> str:
            await asyncio.sleep(10)  # Долгий worker
            return _final_envelope("done")

        orchestrator = ThinSubagentOrchestrator(
            max_concurrent=2,
            llm_call=fake_llm,
            runtime_config=RuntimeConfig(runtime_name="thin"),
        )

        spec = SubagentSpec(name="w", system_prompt="test")
        await orchestrator.spawn(spec, "task1")
        await orchestrator.spawn(spec, "task2")

        with pytest.raises(ValueError, match="max_concurrent"):
            await orchestrator.spawn(spec, "task3")

        # Cleanup
        active = await orchestrator.list_active()
        for aid in active:
            await orchestrator.cancel(aid)

    @pytest.mark.asyncio
    async def test_subagent_cancel(self) -> None:
        """Cancel subagent -> status = cancelled."""
        async def fake_llm(messages: list, system_prompt: str, **kwargs: Any) -> str:
            await asyncio.sleep(10)
            return _final_envelope("should not reach")

        orchestrator = ThinSubagentOrchestrator(
            max_concurrent=4,
            llm_call=fake_llm,
            runtime_config=RuntimeConfig(runtime_name="thin"),
        )

        spec = SubagentSpec(name="cancellable", system_prompt="test")
        agent_id = await orchestrator.spawn(spec, "long task")

        await asyncio.sleep(0.05)
        await orchestrator.cancel(agent_id)

        result = await orchestrator.wait(agent_id)
        assert result.status.state == "cancelled"
