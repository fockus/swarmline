"""Thin Subagent module."""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from cognitia.orchestration.runtime_helpers import collect_runtime_output
from cognitia.orchestration.subagent_types import (
    SubagentResult,
    SubagentSpec,
    SubagentStatus,
)
from cognitia.runtime.thin.runtime import ThinRuntime
from cognitia.runtime.types import Message, RuntimeConfig


class _SubagentRuntime(Protocol):
    """Mandandmal interface runtime for subagent."""

    async def run(self, task: str) -> str: ...


class ThinSubagentOrchestrator:
    """Ortoestrator subagent'oin on asyncio.Task.

  SRP: manages lifecycle (spawn/cancel/wait), not LLM-logandtoy.
  Prand onlandandand LLM_call - creates a per-worker ThinRuntime aintomatandchestoand.
  """

    def __init__(
        self,
        max_concurrent: int = 4,
        *,
        llm_call: Callable[..., Any] | None = None,
        local_tools: dict[str, Callable[..., Any]] | None = None,
        mcp_servers: dict[str, Any] | None = None,
        runtime_config: RuntimeConfig | None = None,
    ) -> None:
        self._max_concurrent = max_concurrent
        self._llm_call = llm_call
        self._local_tools: dict[str, Callable[..., Any]] = dict(local_tools or {})
        self._mcp_servers = mcp_servers
        self._runtime_config = runtime_config or RuntimeConfig(runtime_name="thin")
        self._tasks: dict[str, asyncio.Task[str]] = {}
        self._specs: dict[str, SubagentSpec] = {}
        self._results: dict[str, SubagentResult] = {}

    def register_tool(self, name: str, executor: Callable[..., Any]) -> None:
        """Register a tool available to all spawned workers."""
        self._local_tools[name] = executor

    def _create_runtime(self, spec: SubagentSpec) -> _SubagentRuntime:
        """Create runtime."""
        return _ThinWorkerRuntime(
            spec=spec,
            llm_call=self._llm_call,
            local_tools=self._local_tools,
            mcp_servers=self._mcp_servers,
            runtime_config=self._runtime_config,
        )

    async def spawn(self, spec: SubagentSpec, task: str) -> str:
        """Run subagent. Returns agent_id."""
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
        """Run agent."""
        started = datetime.now(tz=UTC)
        try:
            output = await runtime.run(task)
            self._results[agent_id] = SubagentResult(
                agent_id=agent_id,
                status=SubagentStatus(
                    state="completed",
                    result=output,
                    started_at=started,
                    finished_at=datetime.now(tz=UTC),
                ),
                output=output,
            )
            return output
        except asyncio.CancelledError:
            self._results[agent_id] = SubagentResult(
                agent_id=agent_id,
                status=SubagentStatus(
                    state="cancelled", started_at=started, finished_at=datetime.now(tz=UTC)
                ),
                output="",
            )
            return ""
        except Exception as e:
            self._results[agent_id] = SubagentResult(
                agent_id=agent_id,
                status=SubagentStatus(
                    state="failed",
                    error=str(e),
                    started_at=started,
                    finished_at=datetime.now(tz=UTC),
                ),
                output="",
            )
            return ""

    async def get_status(self, agent_id: str) -> SubagentStatus:
        """Get status."""
        if agent_id in self._results:
            return self._results[agent_id].status

        task = self._tasks.get(agent_id)
        if task is None:
            return SubagentStatus(state="pending")
        if task.done():
            # Result is not ready yet - we wait a little
            await asyncio.sleep(0)
            if agent_id in self._results:
                return self._results[agent_id].status
            return SubagentStatus(state="completed")
        return SubagentStatus(state="running")

    async def cancel(self, agent_id: str) -> None:
        """Cancel subagent."""
        task = self._tasks.get(agent_id)
        if task and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def wait(self, agent_id: str) -> SubagentResult:
        """Wait for the subagent to complete."""
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
        """List active."""
        return [aid for aid, task in self._tasks.items() if not task.done()]


class _ThinWorkerRuntime:
    """Adapter SubagentSpec -> ThinRuntime.run() for per-worker execution."""

    def __init__(
        self,
        *,
        spec: SubagentSpec,
        llm_call: Callable[..., Any] | None,
        local_tools: dict[str, Callable[..., Any]],
        mcp_servers: dict[str, Any] | None,
        runtime_config: RuntimeConfig,
    ) -> None:
        self._spec = spec
        self._llm_call = llm_call
        self._local_tools = local_tools
        self._mcp_servers = mcp_servers
        self._runtime_config = runtime_config

    async def run(self, task: str) -> str:
        """Run."""
        kwargs: dict[str, Any] = {
            "config": self._runtime_config,
            "local_tools": self._local_tools,
            "mcp_servers": self._mcp_servers,
        }
        if self._llm_call is not None:
            kwargs["llm_call"] = self._llm_call
        runtime = ThinRuntime(**kwargs)
        return await collect_runtime_output(
            runtime.run(
                messages=[Message(role="user", content=task)],
                system_prompt=self._spec.system_prompt,
                active_tools=self._spec.tools,
                mode_hint="react",
            ),
            error_prefix="ThinRuntime subagent error",
        )
