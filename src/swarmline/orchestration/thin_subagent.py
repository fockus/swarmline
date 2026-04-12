"""Thin Subagent module."""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

from swarmline.orchestration.runtime_helpers import collect_runtime_output
from swarmline.orchestration.subagent_types import (
    SubagentResult,
    SubagentSpec,
    SubagentStatus,
)
from swarmline.runtime.thin.runtime import ThinRuntime
from swarmline.runtime.types import Message, RuntimeConfig

if TYPE_CHECKING:
    from swarmline.hooks.registry import HookRegistry
    from swarmline.policy.tool_policy import DefaultToolPolicy
    from swarmline.runtime.thin.coding_profile import CodingProfileConfig


class _SubagentRuntime(Protocol):
    """Minimal runtime interface for subagent execution."""

    async def run(self, task: str) -> str: ...


class ThinSubagentOrchestrator:
    """Orchestrate subagents as asyncio.Tasks.

    SRP: manages lifecycle (spawn/cancel/wait), delegates LLM execution
    to per-worker ThinRuntime instances.
    """

    def __init__(
        self,
        max_concurrent: int = 4,
        *,
        llm_call: Callable[..., Any] | None = None,
        local_tools: dict[str, Callable[..., Any]] | None = None,
        mcp_servers: dict[str, Any] | None = None,
        runtime_config: RuntimeConfig | None = None,
        coding_profile: CodingProfileConfig | None = None,
        tool_policy: DefaultToolPolicy | None = None,
        hook_registry: HookRegistry | None = None,
    ) -> None:
        self._max_concurrent = max_concurrent
        self._llm_call = llm_call
        self._local_tools: dict[str, Callable[..., Any]] = dict(local_tools or {})
        self._mcp_servers = mcp_servers
        self._runtime_config = runtime_config or RuntimeConfig(runtime_name="thin")
        self._coding_profile = coding_profile
        self._tool_policy = tool_policy
        self._hook_registry = hook_registry
        self._tasks: dict[str, asyncio.Task[str]] = {}
        self._specs: dict[str, SubagentSpec] = {}
        self._results: dict[str, SubagentResult] = {}

    def register_tool(self, name: str, executor: Callable[..., Any]) -> None:
        """Register a tool available to all spawned workers."""
        self._local_tools[name] = executor

    def _create_runtime(self, spec: SubagentSpec) -> _SubagentRuntime:
        """Create runtime.

        When parent has an active coding_profile, validates that the child
        spec has a sandbox_config (CSUB-03: fail fast on incompatible state).
        """
        if (
            self._coding_profile is not None
            and self._coding_profile.enabled
            and spec.sandbox_config is None
        ):
            raise ValueError(
                f"Subagent '{spec.name}' cannot inherit coding profile: "
                "sandbox_config is required but not provided in SubagentSpec. "
                "Either provide sandbox_config or disable the coding profile."
            )

        return _ThinWorkerRuntime(
            spec=spec,
            llm_call=self._llm_call,
            local_tools=self._local_tools,
            mcp_servers=self._mcp_servers,
            runtime_config=self._runtime_config,
            tool_policy=self._tool_policy,
            hook_registry=self._hook_registry,
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
        tool_policy: DefaultToolPolicy | None = None,
        hook_registry: HookRegistry | None = None,
    ) -> None:
        self._spec = spec
        self._llm_call = llm_call
        self._local_tools = local_tools
        self._mcp_servers = mcp_servers
        self._runtime_config = runtime_config
        self._tool_policy = tool_policy
        self._hook_registry = hook_registry

    async def run(self, task: str) -> str:
        """Run."""
        kwargs: dict[str, Any] = {
            "config": self._runtime_config,
            "local_tools": self._local_tools,
            "mcp_servers": self._mcp_servers,
        }
        if self._llm_call is not None:
            kwargs["llm_call"] = self._llm_call
        if self._tool_policy is not None:
            kwargs["tool_policy"] = self._tool_policy
        if self._hook_registry is not None:
            kwargs["hook_registry"] = self._hook_registry
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
