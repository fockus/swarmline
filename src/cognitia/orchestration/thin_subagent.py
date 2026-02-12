"""ThinSubagentOrchestrator — subagent'ы через asyncio.Task.

Каждый subagent = asyncio.Task с собственным runtime.
Bounded: max_concurrent ограничивает параллельные задачи.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from datetime import datetime, timezone
from typing import Protocol

from cognitia.orchestration.subagent_types import (
    SubagentResult,
    SubagentSpec,
    SubagentStatus,
)


class _SubagentRuntime(Protocol):
    """Минимальный интерфейс runtime для subagent."""

    async def run(self, task: str) -> str: ...


class ThinSubagentOrchestrator:
    """Оркестратор subagent'ов на asyncio.Task.

    SRP: управляет lifecycle (spawn/cancel/wait), не LLM-логикой.
    """

    def __init__(self, max_concurrent: int = 4) -> None:
        self._max_concurrent = max_concurrent
        self._tasks: dict[str, asyncio.Task[str]] = {}
        self._specs: dict[str, SubagentSpec] = {}
        self._results: dict[str, SubagentResult] = {}

    def _create_runtime(self, spec: SubagentSpec) -> _SubagentRuntime:
        """Создать runtime для subagent'а. Override в тестах."""
        raise NotImplementedError("Инъектируйте _create_runtime")

    async def spawn(self, spec: SubagentSpec, task: str) -> str:
        """Запустить subagent. Возвращает agent_id."""
        active_count = sum(1 for t in self._tasks.values() if not t.done())
        if active_count >= self._max_concurrent:
            msg = f"Достигнут лимит max_concurrent ({self._max_concurrent})"
            raise ValueError(msg)

        agent_id = str(uuid.uuid4())
        self._specs[agent_id] = spec

        runtime = self._create_runtime(spec)
        coro = self._run_agent(agent_id, runtime, task)
        self._tasks[agent_id] = asyncio.create_task(coro)
        return agent_id

    async def _run_agent(self, agent_id: str, runtime: _SubagentRuntime, task: str) -> str:
        """Выполнить subagent — обёрнуть в try/except для graceful failure."""
        started = datetime.now(tz=timezone.utc)
        try:
            output = await runtime.run(task)
            self._results[agent_id] = SubagentResult(
                agent_id=agent_id,
                status=SubagentStatus(state="completed", result=output, started_at=started, finished_at=datetime.now(tz=timezone.utc)),
                output=output,
            )
            return output
        except asyncio.CancelledError:
            self._results[agent_id] = SubagentResult(
                agent_id=agent_id,
                status=SubagentStatus(state="cancelled", started_at=started, finished_at=datetime.now(tz=timezone.utc)),
                output="",
            )
            return ""
        except Exception as e:
            self._results[agent_id] = SubagentResult(
                agent_id=agent_id,
                status=SubagentStatus(state="failed", error=str(e), started_at=started, finished_at=datetime.now(tz=timezone.utc)),
                output="",
            )
            return ""

    async def get_status(self, agent_id: str) -> SubagentStatus:
        """Получить статус subagent'а."""
        if agent_id in self._results:
            return self._results[agent_id].status

        task = self._tasks.get(agent_id)
        if task is None:
            return SubagentStatus(state="pending")
        if task.done():
            # Результат ещё не записан — ждём чуть-чуть
            await asyncio.sleep(0)
            if agent_id in self._results:
                return self._results[agent_id].status
            return SubagentStatus(state="completed")
        return SubagentStatus(state="running")

    async def cancel(self, agent_id: str) -> None:
        """Отменить subagent."""
        task = self._tasks.get(agent_id)
        if task and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def wait(self, agent_id: str) -> SubagentResult:
        """Дождаться завершения subagent'а."""
        task = self._tasks.get(agent_id)
        if task:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

        if agent_id in self._results:
            return self._results[agent_id]

        return SubagentResult(
            agent_id=agent_id,
            status=SubagentStatus(state="pending"),
            output="",
        )

    async def list_active(self) -> list[str]:
        """Список активных subagent id'ов."""
        return [aid for aid, task in self._tasks.items() if not task.done()]
