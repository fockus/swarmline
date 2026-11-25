"""Thin Subagent module."""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

from swarmline.domain_types import RuntimeEvent
from swarmline.multi_agent.workspace_types import (
    WorkspaceHandle,
    WorkspaceSpec,
    WorkspaceStrategy,
)
from swarmline.orchestration.context_bridge import ContextBridgeBuilder
from swarmline.orchestration.runtime_helpers import collect_runtime_output
from swarmline.orchestration.subagent_types import (
    SubagentResult,
    SubagentSpec,
    SubagentStatus,
)
from swarmline.runtime.registry import RuntimeRegistry
from swarmline.runtime.thin.runtime import ThinRuntime
from swarmline.runtime.types import Message, RuntimeConfig

if TYPE_CHECKING:
    from swarmline.governance.protocols import SecretBoundaryPort
    from swarmline.hooks.registry import HookRegistry
    from swarmline.multi_agent.workspace import ExecutionWorkspace
    from swarmline.policy.tool_policy import DefaultToolPolicy
    from swarmline.runtime.thin.coding_profile import CodingProfileConfig


def _build_system_prompt(spec: SubagentSpec) -> str:
    """Build system prompt, prepending context bridge if present."""
    if spec.context_bridge is not None:
        bridge_section = ContextBridgeBuilder.format_for_prompt(spec.context_bridge)
        return f"{bridge_section}\n\n{spec.system_prompt}"
    return spec.system_prompt


class _SubagentRuntime(Protocol):
    """Minimal runtime interface for subagent execution."""

    async def run(self, task: str) -> str: ...


# Parent-run bound native_config keys a spawned child must not inherit: the live
# plan provider (and the recitation settings around it) describe the PARENT's
# plan — a child reciting it would work on someone else's todo list.
_PARENT_RUN_NATIVE_KEYS = frozenset(
    {
        "recitation_plan_provider",
        "recitation_round_cadence",
        "recitation_mode",
        "recitation_plan_text",
        "recitation_plan_summary_text",
        "recitation_cadence",
    }
)


def child_runtime_config(config: RuntimeConfig) -> RuntimeConfig:
    """The parent's runtime config minus its plan recitation: the parent-run bound
    ``native_config`` keys and the ``RecitationInputFilter`` built from them."""
    from swarmline.context.recitation_input_filter import RecitationInputFilter

    filters = [
        f for f in config.input_filters if not isinstance(f, RecitationInputFilter)
    ]
    if len(filters) == len(config.input_filters) and not (
        _PARENT_RUN_NATIVE_KEYS & config.native_config.keys()
    ):
        return config
    native = {
        k: v
        for k, v in config.native_config.items()
        if k not in _PARENT_RUN_NATIVE_KEYS
    }
    return replace(config, native_config=native, input_filters=filters)


class ThinSubagentOrchestrator:
    """Orchestrate subagents as asyncio.Tasks.

    SRP: manages lifecycle (spawn/cancel/wait), delegates LLM execution
    to per-worker ThinRuntime instances. When given llm_call — creates a
    per-worker ThinRuntime automatically.
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
        can_use_tool: Callable[..., Awaitable[Any]] | None = None,
        on_background_complete: Callable[[RuntimeEvent], Awaitable[None]] | None = None,
        background_timeout: float | None = None,
        on_result_callback: Callable[[str, SubagentResult], None] | None = None,
        lessons_extractor: Any | None = None,
        lessons_store: Any | None = None,
        registry: RuntimeRegistry | None = None,
        secret_boundary: SecretBoundaryPort | None = None,
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
        self._runtime_config = child_runtime_config(
            runtime_config or RuntimeConfig(runtime_name="thin")
        )
        self._coding_profile = coding_profile
        self._tool_policy = tool_policy
        self._hook_registry = hook_registry
        self._can_use_tool = can_use_tool
        self._on_background_complete = on_background_complete
        self._background_timeout = background_timeout
        self._on_result_callback = on_result_callback
        self._lessons_extractor = lessons_extractor
        self._lessons_store = lessons_store
        self._registry = registry
        # REQ-ORC-044 (fix-cycle 2): scans background-complete events and the
        # SubagentResult handed to on_result_callback — the foreground JSON
        # return (create_subagent_executor) and monitor_agent
        # (create_monitor_executor) each carry their OWN secret_boundary at
        # the wrapper level; this one covers the two paths that have no
        # wrapper of their own. Default None preserves legacy raw passthrough.
        self._secret_boundary = secret_boundary
        self._tasks: dict[str, asyncio.Task[str]] = {}
        self._specs: dict[str, SubagentSpec] = {}
        self._results: dict[str, SubagentResult] = {}
        self._output_buffers: dict[str, str] = {}

    def register_tool(self, name: str, executor: Callable[..., Any]) -> None:
        """Register a tool available to all spawned workers."""
        self._local_tools[name] = executor

    def _create_runtime(self, spec: SubagentSpec) -> _SubagentRuntime:
        """Create runtime.

        When spec.runtime_name is set, resolves the runtime ONLY through the
        RuntimeRegistry (REQ-RCA-050/051). An unknown name fails fast with an
        error naming the missing runtime (REQ-RCA-052).

        When runtime_name is None (default), the current _ThinWorkerRuntime
        path is used byte-identical to the pre-Task-7 behaviour.

        When parent has an active coding_profile, validates that the child
        spec has a sandbox_config (CSUB-03: fail fast on incompatible state).
        """
        if spec.runtime_name is not None:
            return self._create_registry_runtime(spec)

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
            can_use_tool=self._can_use_tool,
            coding_profile=self._coding_profile,
        )

    def _create_registry_runtime(self, spec: SubagentSpec) -> _SubagentRuntime:
        """Resolve runtime_name through the RuntimeRegistry and return a worker.

        Fail-fast (REQ-RCA-052): raises ValueError naming the missing runtime
        when runtime_name is not registered. NEVER falls back to a default.
        """
        from swarmline.runtime.registry import get_default_registry

        registry = (
            self._registry if self._registry is not None else get_default_registry()
        )
        assert (
            spec.runtime_name is not None
        )  # invariant: only called when runtime_name is set
        name: str = spec.runtime_name
        factory_fn = registry.get(name)
        if factory_fn is None:
            available = set(registry.list_available())
            raise ValueError(f"Unknown runtime '{name}'; registered: {available}")
        return _RegistryWorkerRuntime(
            spec=spec,
            factory_fn=factory_fn,
            runtime_config=self._runtime_config,
            llm_call=self._llm_call,
            local_tools=self._local_tools,
            mcp_servers=self._mcp_servers,
            tool_policy=self._tool_policy,
            hook_registry=self._hook_registry,
            can_use_tool=self._can_use_tool,
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
                raise ValueError("base_path is required for worktree isolation")
            if len(self._worktree_handles) >= self._max_worktrees:
                raise ValueError(f"Max worktrees limit ({self._max_worktrees}) reached")
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
                runtime._cwd = handle.path  # ty: ignore[invalid-assignment]  # _cwd narrowed via hasattr check above; ty doesn't propagate

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

    async def _run_agent(
        self, agent_id: str, runtime: _SubagentRuntime, task: str
    ) -> str:
        """Run agent with worktree cleanup in finally."""
        started = datetime.now(tz=UTC)
        try:
            output = await runtime.run(task)
            result = SubagentResult(
                agent_id=agent_id,
                status=SubagentStatus(
                    state="completed",
                    result=output,
                    started_at=started,
                    finished_at=datetime.now(tz=UTC),
                ),
                output=output,
            )
            self._results[agent_id] = result
            self._fire_callback(agent_id, result)
            return output
        except asyncio.CancelledError:
            result = SubagentResult(
                agent_id=agent_id,
                status=SubagentStatus(
                    state="cancelled",
                    started_at=started,
                    finished_at=datetime.now(tz=UTC),
                ),
                output="",
            )
            self._results[agent_id] = result
            self._fire_callback(agent_id, result)
            return ""
        except Exception as e:
            result = SubagentResult(
                agent_id=agent_id,
                status=SubagentStatus(
                    state="failed",
                    error=str(e),
                    started_at=started,
                    finished_at=datetime.now(tz=UTC),
                ),
                output="",
            )
            self._results[agent_id] = result
            self._fire_callback(agent_id, result)
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
        """Emit background_complete event via callback if registered.

        `result`/`error` are scanned via `secret_boundary` before being
        embedded in the event (REQ-ORC-044) — the background path has no
        `create_subagent_executor`-style wrapper of its own to redact at.
        """
        if self._on_background_complete is not None:
            if self._secret_boundary is not None:
                if result is not None:
                    result = self._secret_boundary.redact(result)
                if error is not None:
                    error = self._secret_boundary.redact(error)
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
            self._stale_cleanup_task = asyncio.create_task(self._run_stale_cleanup())

    async def _run_stale_cleanup(self) -> None:
        """Execute the stale cleanup callback (fire-and-forget)."""
        try:
            if self._stale_cleanup_fn is not None:
                await self._stale_cleanup_fn()
        except Exception:  # noqa: BLE001
            pass  # fire-and-forget, must not crash orchestrator

    def _scan_result(self, result: SubagentResult) -> SubagentResult:
        """Return a secret-boundary-scanned COPY of `result` (REQ-ORC-044).

        Redacts `.output`, `.status.error`, AND `.status.result` — all three
        fields that carry the untrusted child's free-text content
        (`_run_agent`'s success branch sets `status=SubagentStatus(result=output)`
        alongside the top-level `.output`, so `.status.result` carries the
        SAME raw text as `.output` and must be scanned too — round-3 review
        finding). Shared by every LLM/host-facing exit point that reads a
        `SubagentResult` off this orchestrator: `_fire_callback`
        (`on_result_callback`) and `wait()` (consumed by
        `create_subagent_executor`'s own JSON scan, but ALSO directly by
        `supervisor/tools.py::_spawn_and_wait` → `Report.summary` →
        `read_reports`, `supervisor/replan.py::plan_via_subagent`, and
        `tools/research.py::spawn_research` — none of which re-scan). No-op
        (returns `result` unchanged) when no boundary is configured.
        """
        if self._secret_boundary is None:
            return result
        return replace(
            result,
            output=self._secret_boundary.redact(result.output),
            status=replace(
                result.status,
                error=(
                    self._secret_boundary.redact(result.status.error)
                    if result.status.error is not None
                    else None
                ),
                result=(
                    self._secret_boundary.redact(result.status.result)
                    if result.status.result is not None
                    else None
                ),
            ),
        )

    def _fire_callback(self, agent_id: str, result: SubagentResult) -> None:
        """Fire on_result_callback if registered, then extract lessons.

        `on_result_callback` receives a secret-boundary-scanned COPY of
        `result` (REQ-ORC-044) — the untrusted child's raw output/error must
        not reach a host-supplied callback unredacted. Lessons extraction
        below still reads the ORIGINAL `result.output` (internal-only, never
        re-enters an LLM context directly through this path).
        """
        if self._on_result_callback is not None:
            self._on_result_callback(agent_id, self._scan_result(result))
        if (
            self._lessons_extractor is not None
            and self._lessons_store is not None
            and result.output
        ):
            spec = self._specs.get(agent_id)
            goal = spec.system_prompt if spec else "unknown"
            for lesson in self._lessons_extractor.extract(result.output, goal):
                self._lessons_store.add(lesson)

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
        """Wait for the subagent to complete.

        Returns a secret-boundary-scanned COPY when a boundary is configured
        (REQ-ORC-044, fix-cycle 3): `wait()` is the LLM/host-facing exit
        point for `supervisor/tools.py`, `supervisor/replan.py`, and
        `tools/research.py` — none of which re-scan the result themselves.
        `self._results` keeps the RAW value internally (read by
        `get_status()`/`_fire_callback`'s lessons-extraction branch); only
        the value handed back to the CALLER of `wait()` is scanned.
        """
        task = self._tasks.get(agent_id)
        if task:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

        if agent_id in self._results:
            return self._scan_result(self._results[agent_id])

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
        can_use_tool: Callable[..., Awaitable[Any]] | None = None,
        coding_profile: CodingProfileConfig | None = None,
    ) -> None:
        self._spec = spec
        self._llm_call = llm_call
        self._local_tools = local_tools
        self._mcp_servers = mcp_servers
        self._runtime_config = runtime_config
        self._tool_policy = tool_policy
        self._hook_registry = hook_registry
        self._can_use_tool = can_use_tool
        self._coding_profile = coding_profile
        self._cwd: str | None = None

    def _build_runtime_local_tools(self) -> dict[str, Callable[..., Any]]:
        """Rebind coding sandbox tools to the worker worktree when available."""
        if self._cwd is None or self._spec.sandbox_config is None:
            return self._local_tools

        from swarmline.runtime.thin.coding_toolpack import build_coding_toolpack
        from swarmline.tools.sandbox_local import LocalSandboxProvider
        from swarmline.tools.types import SandboxConfig

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
        # F5 fix: build the worktree pack first so its tool surface (which includes
        # multi_file_edit when edit_strategy != "legacy") defines exactly which tools
        # to rebind — not the hard-coded CODING_SANDBOX_TOOL_NAMES constant that
        # predates the opt-in tools added in Task 1.
        coding_pack = build_coding_toolpack(
            worktree_sandbox, config=self._coding_profile
        )

        # Rebind every tool the worktree pack provides AND the parent has registered.
        # This naturally includes multi_file_edit (non-legacy) and excludes todo/MCP
        # tools that the pack doesn't provide.
        tool_names_to_rebind = set(coding_pack.specs) & set(self._local_tools)
        if not tool_names_to_rebind:
            return self._local_tools

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
        # REQ-ORC-043: thread the child's own recursion depth (set by
        # create_subagent_executor to parent_current_depth + 1) so the
        # depth-guard is real across a spawn hop, not hardcoded 0. Inert
        # when this worker has no subagent_config of its own (the common
        # case today — no working spawn_agent executor is registered, so
        # nothing ever reads current_depth on the child).
        kwargs["current_depth"] = self._spec.depth
        if self._can_use_tool is not None:
            kwargs["can_use_tool"] = self._can_use_tool

        runtime = ThinRuntime(**kwargs)
        system_prompt = _build_system_prompt(self._spec)
        return await collect_runtime_output(
            runtime.run(
                messages=[Message(role="user", content=task)],
                system_prompt=system_prompt,
                active_tools=self._spec.tools,
                mode_hint="react",
            ),
            error_prefix="ThinRuntime subagent error",
        )


class _RegistryWorkerRuntime:
    """Adapts a RuntimeRegistry-resolved factory to the _SubagentRuntime interface.

    Created by ThinSubagentOrchestrator._create_registry_runtime when
    SubagentSpec.runtime_name is set (REQ-RCA-050/051).  The factory is called
    fresh on each run() invocation so the runtime object is never shared across
    concurrent workers.
    """

    def __init__(
        self,
        *,
        spec: SubagentSpec,
        factory_fn: Callable[..., Any],
        runtime_config: RuntimeConfig,
        llm_call: Callable[..., Any] | None,
        local_tools: dict[str, Callable[..., Any]],
        mcp_servers: dict[str, Any] | None,
        tool_policy: Any | None,
        hook_registry: Any | None,
        can_use_tool: Any | None = None,
    ) -> None:
        self._spec = spec
        self._factory_fn = factory_fn
        self._runtime_config = runtime_config
        self._llm_call = llm_call
        self._local_tools = local_tools
        self._mcp_servers = mcp_servers
        self._tool_policy = tool_policy
        self._hook_registry = hook_registry
        self._can_use_tool = can_use_tool
        self._cwd: str | None = None

    async def run(self, task: str) -> str:
        """Instantiate the registered runtime and collect its output stream."""
        kwargs: dict[str, Any] = {}
        if self._llm_call is not None:
            kwargs["llm_call"] = self._llm_call
        if self._local_tools:
            kwargs["local_tools"] = dict(self._local_tools)
        if self._mcp_servers is not None:
            kwargs["mcp_servers"] = self._mcp_servers
        if self._tool_policy is not None:
            kwargs["tool_policy"] = self._tool_policy
        if self._hook_registry is not None:
            kwargs["hook_registry"] = self._hook_registry
        if self._can_use_tool is not None:
            # Mirrors the existing (ungated) tool_policy forwarding above: the
            # registry path already forwards tool_policy to whatever runtime
            # is resolved by name, regardless of whether that runtime's
            # constructor understands it (a pre-existing, unfixed gap of the
            # same shape — I-100-adjacent). can_use_tool follows the SAME
            # precedent rather than inventing new per-runtime-name gating;
            # a registered factory that doesn't accept this kwarg fails the
            # same way tool_policy already would.
            kwargs["can_use_tool"] = self._can_use_tool

        runtime = self._factory_fn(self._runtime_config, **kwargs)
        system_prompt = _build_system_prompt(self._spec)
        return await collect_runtime_output(
            runtime.run(
                messages=[Message(role="user", content=task)],
                system_prompt=system_prompt,
                active_tools=self._spec.tools,
                mode_hint="react",
            ),
            error_prefix=f"registry subagent (runtime='{self._spec.runtime_name}')",
        )
