"""Thin Subagent module."""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

from swarmline.multi_agent.workspace_types import (
    WorkspaceHandle,
    WorkspaceSpec,
    WorkspaceStrategy,
)

from swarmline.domain_types import RuntimeEvent
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
    from swarmline.multi_agent.workspace import ExecutionWorkspace
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
        max_worktrees: int = 5,
        base_path: str | None = None,
        workspace: ExecutionWorkspace | None = None,
        stale_cleanup_fn: Callable[[], Awaitable[None]] | None = None,
        llm_call: Callable[..., Any] | None = None,
        local_tools: dict[str, Callable[..., Any]] | None = None,
        mcp_servers: dict[str, Any] | None = None,
        runtime_config: RuntimeConfig | None = None,
        coding_profile: CodingProfileConfig | None = None,
        tool_policy: DefaultToolPolicy | None = None,
        hook_registry: HookRegistry | None = None,
        on_background_complete: Callable[[RuntimeEvent], Awaitable[None]] | None = None,
        background_timeout: float | None = None,
    ) -> None:
        self._max_concurrent = max_concurrent
        self._max_worktrees = max_worktrees
        self._base_path = base_path
        self._workspace = workspace
        self._stale_cleanup_fn = stale_cleanup_fn
        self._stale_cleanup_done = False
        self._stale_cleanup_task: asyncio.Task[None] | None = None
        self._worktree_handles: dict[str, WorkspaceHandle] = {}
        self._llm_call = llm_call
        self._local_tools: dict[str, Callable[..., Any]] = dict(local_tools or {})
        self._mcp_servers = mcp_servers
        self._runtime_config = runtime_config or RuntimeConfig(runtime_name="thin")
        self._coding_profile = coding_profile
        self._tool_policy = tool_policy
        self._hook_registry = hook_registry
        self._on_background_complete = on_background_complete
        self._background_timeout = background_timeout
        self._tasks: dict[str, asyncio.Task[str]] = {}
        self._specs: dict[str, SubagentSpec] = {}
        self._results: dict[str, SubagentResult] = {}
        self._output_buffers: dict[str, str] = {}

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
        if spec.isolation is not None and spec.isolation != "worktree":
            raise ValueError(
                f"Invalid isolation mode: {spec.isolation!r}, "
                "only 'worktree' is supported"
            )
        if spec.isolation == "worktree":
            if self._base_path is None:
                raise ValueError(
                    "base_path is required for worktree isolation"
                )
            if len(self._worktree_handles) >= self._max_worktrees:
                raise ValueError(
                    f"Max worktrees limit ({self._max_worktrees}) reached"
                )
            self._ensure_stale_cleanup()

        active_count = sum(1 for t in self._tasks.values() if not t.done())
        if active_count >= self._max_concurrent:
            msg = f"Достигнут лимит max_concurrent ({self._max_concurrent})"
            raise ValueError(msg)

        agent_id = str(uuid.uuid4())
        self._specs[agent_id] = spec

        handle: WorkspaceHandle | None = None
        try:
            if spec.isolation == "worktree":
                handle = await self._create_worktree(agent_id, spec)
                self._worktree_handles[agent_id] = handle

            runtime = self._create_runtime(spec)
            if handle is not None and hasattr(runtime, "_cwd"):
                runtime._cwd = handle.path  # type: ignore[union-attr]

            if spec.run_in_background:
                coro = self._run_background_agent(agent_id, runtime, task)
            else:
                coro = self._run_agent(agent_id, runtime, task)
            self._tasks[agent_id] = asyncio.create_task(coro)
            return agent_id
        except Exception:
            if handle is not None:
                self._worktree_handles.pop(agent_id, None)
                await self._cleanup_worktree(handle)
            raise

    async def _run_agent(self, agent_id: str, runtime: _SubagentRuntime, task: str) -> str:
        """Run agent with worktree cleanup in finally."""
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
        finally:
            handle = self._worktree_handles.pop(agent_id, None)
            if handle is not None:
                await self._cleanup_worktree(handle)

    async def _run_background_agent(
        self, agent_id: str, runtime: _SubagentRuntime, task: str
    ) -> str:
        """Run agent in background with optional timeout and completion event."""
        started = datetime.now(tz=UTC)
        try:
            coro = runtime.run(task)
            if self._background_timeout is not None:
                output = await asyncio.wait_for(coro, timeout=self._background_timeout)
            else:
                output = await coro
            self._output_buffers[agent_id] = output
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
            await self._emit_background_complete(agent_id, result=output)
            return output
        except asyncio.TimeoutError:
            error_msg = f"Background agent {agent_id} timed out"
            self._results[agent_id] = SubagentResult(
                agent_id=agent_id,
                status=SubagentStatus(
                    state="failed",
                    error=error_msg,
                    started_at=started,
                    finished_at=datetime.now(tz=UTC),
                ),
                output="",
            )
            await self._emit_background_complete(agent_id, error=error_msg)
            return ""
        except asyncio.CancelledError:
            self._results[agent_id] = SubagentResult(
                agent_id=agent_id,
                status=SubagentStatus(
                    state="cancelled",
                    started_at=started,
                    finished_at=datetime.now(tz=UTC),
                ),
                output="",
            )
            return ""
        except Exception as e:
            error_msg = str(e)
            self._results[agent_id] = SubagentResult(
                agent_id=agent_id,
                status=SubagentStatus(
                    state="failed",
                    error=error_msg,
                    started_at=started,
                    finished_at=datetime.now(tz=UTC),
                ),
                output="",
            )
            await self._emit_background_complete(agent_id, error=error_msg)
            return ""
        finally:
            handle = self._worktree_handles.pop(agent_id, None)
            if handle is not None:
                await self._cleanup_worktree(handle)

    async def _emit_background_complete(
        self,
        agent_id: str,
        result: str | None = None,
        error: str | None = None,
    ) -> None:
        """Emit background_complete event via callback if registered."""
        if self._on_background_complete is not None:
            event = RuntimeEvent.background_complete(
                agent_id=agent_id, result=result, error=error
            )
            try:
                await self._on_background_complete(event)
            except Exception:  # noqa: BLE001
                pass  # callback failure must not crash agent lifecycle

    def get_output(self, agent_id: str) -> str:
        """Return buffered output for a background agent."""
        return self._output_buffers.get(agent_id, "")

    async def _create_worktree(
        self, agent_id: str, spec: SubagentSpec
    ) -> WorkspaceHandle:
        """Create a git worktree workspace for an isolated subagent."""
        if self._workspace is None:
            raise ValueError("workspace is required for worktree isolation")
        if self._base_path is None:
            raise ValueError("base_path is required for worktree isolation")
        uuid_short = uuid.uuid4().hex[:8]
        ws_spec = WorkspaceSpec(
            strategy=WorkspaceStrategy.GIT_WORKTREE,
            base_path=self._base_path,
            branch_template="swarmline/{agent_name}/{task_id}",
        )
        return await self._workspace.create(ws_spec, spec.name, uuid_short)

    async def _cleanup_worktree(self, handle: WorkspaceHandle) -> None:
        """Best-effort cleanup — must not propagate exceptions."""
        if self._workspace is not None:
            try:
                await self._workspace.cleanup(handle)
            except Exception:  # noqa: BLE001
                pass  # cleanup errors must not crash the orchestrator

    def _ensure_stale_cleanup(self) -> None:
        """Fire-and-forget stale worktree cleanup, once per lifetime."""
        if self._stale_cleanup_done:
            return
        self._stale_cleanup_done = True
        if self._stale_cleanup_fn is not None:
            self._stale_cleanup_task = asyncio.create_task(
                self._run_stale_cleanup()
            )

    async def _run_stale_cleanup(self) -> None:
        """Execute the stale cleanup callback (fire-and-forget)."""
        try:
            if self._stale_cleanup_fn is not None:
                await self._stale_cleanup_fn()
        except Exception:  # noqa: BLE001
            pass  # fire-and-forget, must not crash orchestrator

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
        self._cwd: str | None = None

    def _build_runtime_local_tools(self) -> dict[str, Callable[..., Any]]:
        """Rebind coding sandbox tools to the worker worktree when available."""
        if self._cwd is None or self._spec.sandbox_config is None:
            return self._local_tools

        from swarmline.runtime.thin.coding_toolpack import (
            CODING_SANDBOX_TOOL_NAMES,
            build_coding_toolpack,
        )
        from swarmline.tools.sandbox_local import LocalSandboxProvider
        from swarmline.tools.types import SandboxConfig

        tool_names_to_rebind = CODING_SANDBOX_TOOL_NAMES & set(self._local_tools)
        if not tool_names_to_rebind:
            return self._local_tools

        sandbox_template = self._spec.sandbox_config
        worktree_sandbox_config = SandboxConfig(
            root_path=self._cwd,
            user_id=sandbox_template.user_id,
            topic_id=sandbox_template.topic_id,
            max_file_size_bytes=sandbox_template.max_file_size_bytes,
            timeout_seconds=sandbox_template.timeout_seconds,
            allowed_extensions=sandbox_template.allowed_extensions,
            denied_commands=sandbox_template.denied_commands,
            allow_host_execution=sandbox_template.allow_host_execution,
        )
        worktree_sandbox = LocalSandboxProvider(worktree_sandbox_config)
        coding_pack = build_coding_toolpack(worktree_sandbox)

        rebound_local_tools = dict(self._local_tools)
        for tool_name in tool_names_to_rebind:
            rebound_local_tools[tool_name] = coding_pack.executors[tool_name]
        return rebound_local_tools

    async def run(self, task: str) -> str:
        """Run the worker without mutating process-global cwd.

        Worktree paths are carried on the worker instance for workspace-aware
        tools and future runtime wiring. The worker itself must not call
        ``os.chdir()``, because subagents execute concurrently in the same
        process and a global cwd switch breaks isolation guarantees.
        """

        kwargs: dict[str, Any] = {
            "config": self._runtime_config,
            "local_tools": self._build_runtime_local_tools(),
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
