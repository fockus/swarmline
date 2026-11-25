"""`CodeAgent` -- the ergonomic public facade (code-agent-facade plan, Stage 5).

Stage 1 pinned the FINAL public constructor + property surface as a
Contract-First skeleton. Stage 2 wired `run`/`stream`/`close` to drive a real
thin runtime with the coding profile: it composes
`AgentConfig(coding_profile=enabled)` + `build_portable_runtime_plan` +
`RuntimeFactoryPort` -- pure reuse of the v1.7.0 wiring already exercised by
`Agent`/`run_portable_runtime`, no new run-loop primitive. Stage 3 fills in
`_augment_plan`: it merges the governance/workspace/scratchpad/code_intel
capability tools (`code_agent._tools`) into the plan's `active_tools`/
`tool_executors`, and -- when `on_permission_request` is supplied -- merges
a PreToolUse permission hook (`code_agent._permission`) into the plan's
`hook_registry`. Stage 4 adds resilience knobs (compaction/evolution) onto
`plan.config`. Stage 5 (this file) adds session lifecycle: `run`/`stream`
now accumulate conversation history across turns (instead of a single
throwaway message per call) and auto-persist it via `code_agent._session`;
`resume`/`reset` reuse `CodeRuntimeSession` + the existing `MessageStore`
backend.
"""

from __future__ import annotations

import dataclasses
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from swarmline.code_agent._permission import build_permission_hook
from swarmline.code_agent._prompts import DEFAULT_CODER_SYSTEM_PROMPT
from swarmline.code_agent._session import (
    FacadeSessionStore,
    build_code_runtime_session,
    build_snapshot,
)
from swarmline.code_agent._tools import assemble_capability_tools
from swarmline.code_agent.types import PermissionCallback
from swarmline.code_runtime_types import CodeRuntimeSession, CodeSessionStatus

if TYPE_CHECKING:
    from swarmline.agent.config import AgentConfig
    from swarmline.agent.runtime_factory_port import RuntimeFactoryPort
    from swarmline.agent.runtime_wiring import PortableRuntimePlan
    from swarmline.agent.tool import ToolDefinition
    from swarmline.runtime.types import Message, RuntimeEvent


def _coerce_tool_definitions(
    tools: tuple[Any, ...] | None,
) -> tuple[ToolDefinition, ...]:
    """Validate `tools` fail-fast at construction time.

    Accepts `ToolDefinition` instances and `@tool`-decorated functions (which
    carry `__tool_definition__` -- the same unwrapping the thin executor
    does). Anything else raises `TypeError` here, instead of surfacing later
    as an obscure `AttributeError` deep inside runtime wiring.
    """
    from swarmline.agent.tool import ToolDefinition

    coerced: list[ToolDefinition] = []
    for entry in tools or ():
        definition = getattr(entry, "__tool_definition__", entry)
        if not isinstance(definition, ToolDefinition):
            raise TypeError(
                "tools entries must be ToolDefinition instances or @tool-"
                f"decorated functions, got {type(entry).__name__!r}"
            )
        coerced.append(definition)
    return tuple(coerced)


class CodeAgent:
    """Compose the thin runtime + coding profile behind one constructor."""

    def __init__(
        self,
        model: str = "sonnet",
        cwd: str | None = None,
        *,
        tools: tuple[Any, ...] | None = None,
        system_prompt: str | None = None,
        on_permission_request: PermissionCallback | None = None,
        runtime_factory: RuntimeFactoryPort | None = None,
        compaction: bool = True,
        evolution: bool = True,
        verify_command: str | None = None,
        session_id: str | None = None,
    ) -> None:
        from swarmline.agent.config import AgentConfig
        from swarmline.agent.runtime_factory_port import build_runtime_factory
        from swarmline.runtime.thin.coding_profile import CodingProfileConfig

        self._model = model or "sonnet"
        self._cwd = cwd if cwd is not None else os.getcwd()
        self._tools = _coerce_tool_definitions(tools)
        self._system_prompt = system_prompt or DEFAULT_CODER_SYSTEM_PROMPT
        self._on_permission_request = on_permission_request
        self._factory = runtime_factory or build_runtime_factory()
        self._compaction_enabled = compaction
        self._evolution_enabled = evolution
        #: Session lifecycle (Stage 5): a fresh UUID4 unless resuming (see
        #: `resume()`, which passes the persisted id back in here).
        self.session_id = session_id or str(uuid.uuid4())
        self.turn_count = 0
        #: Full conversation history, accumulated across `run()`/`stream()`
        #: calls (Stage 2-4 passed only a single throwaway user message per
        #: call; Stage 5 makes `CodeAgent` an actual multi-turn session).
        self._messages: list[Message] = []
        self._created_at = datetime.now(UTC)
        self._status = CodeSessionStatus.CREATED
        self._session_store = FacadeSessionStore()
        #: Runtimes owned by in-flight `run()`/`stream()` calls, keyed by
        #: `id()` -- `RuntimeFactoryPort.create()` returns `Any` and nothing
        #: requires a runtime to be hashable, so a plain set would reject
        #: unhashable runtimes. Membership doubles as the "still needs
        #: cleanup" flag: every cleanup path (generator `finally`, explicit
        #: `close()`) removes the runtime BEFORE awaiting `cleanup()`, so
        #: overlapping paths -- `close()` while a generator is suspended,
        #: `aclose()` after `close()`, concurrent runs -- each clean a
        #: runtime exactly once. Values keep the runtimes alive, so an `id`
        #: cannot be reused while its entry is still in the dict.
        self._active_runtimes: dict[int, Any] = {}
        self._config: AgentConfig = AgentConfig(
            system_prompt=self._system_prompt,
            model=self._model,
            runtime="thin",
            cwd=self._cwd,
            tools=self._tools,
            coding_profile=CodingProfileConfig(enabled=True),
        )
        #: Governance/workspace/scratchpad/code_intel tools, assembled ONCE
        #: per `CodeAgent` instance (not per `run()` call) so stateful
        #: collaborators -- `OwnChangesTracker`, the `WorkspaceSession`, the
        #: in-memory audit trail/scratchpad -- persist across turns instead
        #: of resetting on every call. `verify_command` (Stage 4) is applied
        #: here too -- it only overrides `run_verification`'s DEFAULT test
        #: command, see `_tools._apply_verify_command_override`.
        self._capability_specs, self._capability_executors = assemble_capability_tools(
            self._cwd, verify_command=verify_command
        )
        #: `None` when no `on_permission_request` was supplied -- Stage 3's
        #: documented edge case: no permission hook is registered, but the
        #: coding-profile's scoped `DefaultToolPolicy` still enforces.
        self._permission_hook_registry = (
            build_permission_hook(on_permission_request)
            if on_permission_request is not None
            else None
        )
        #: Stage 4 resilience knobs: `StuckDetector`/`RecoveryCascade` are
        #: pure, stateless domain logic (`evolution/`) -- built once here
        #: (like the capability tools above) and merged into `plan.config`
        #: by `_augment_plan`. `None` on both when `evolution=False`.
        if self._evolution_enabled:
            from swarmline.evolution.recovery import RecoveryCascade
            from swarmline.evolution.stuck_detector import StuckDetector

            self._stuck_detector: Any = StuckDetector()
            self._recovery_cascade: Any = RecoveryCascade()
        else:
            self._stuck_detector = None
            self._recovery_cascade = None

    @property
    def model(self) -> str:
        """Resolved model alias/name (falls back to `"sonnet"`)."""
        return self._model

    @property
    def cwd(self) -> str:
        """Working directory the coding tools are scoped to."""
        return self._cwd

    def _augment_plan(self, plan: PortableRuntimePlan) -> PortableRuntimePlan:
        """Post-process the portable runtime plan before it is executed.

        Merges the governance/workspace/scratchpad/code_intel capability
        tools (assembled once at construction, see `__init__`) into
        `plan.active_tools` / `plan.create_kwargs["tool_executors"]`, and --
        when `on_permission_request` was supplied -- merges the PreToolUse
        permission hook into `plan.create_kwargs["hook_registry"]` (combined
        with whatever hooks the coding profile itself already registered,
        via `HookRegistry.merge`). Also sets the Stage 4 resilience knobs
        (`compaction`/`evolution_enabled`/`stuck_detector`/`recovery_cascade`)
        on `plan.config` -- a fresh `RuntimeConfig` via `dataclasses.replace`
        to keep frozen-style discipline even though `RuntimeConfig` itself is
        a plain mutable dataclass.

        Precedence: an EXISTING active tool/executor -- one the coding
        profile already registered, e.g. `read`/`write`/`bash`, or, when
        `enable_repo_map_ranking` is set, `repo_map` -- always wins over a
        same-named capability tool; the capability tool is skipped rather
        than overwriting it.
        """
        existing_names = {spec.name for spec in plan.active_tools}
        merged_active_tools = list(plan.active_tools) + [
            spec
            for name, spec in self._capability_specs.items()
            if name not in existing_names
        ]

        existing_executors = plan.create_kwargs.get("tool_executors", {})
        merged_create_kwargs = dict(plan.create_kwargs)
        merged_create_kwargs["tool_executors"] = {
            **self._capability_executors,
            **existing_executors,
        }

        if self._permission_hook_registry is not None:
            existing_registry = merged_create_kwargs.get("hook_registry")
            merged_create_kwargs["hook_registry"] = (
                existing_registry.merge(self._permission_hook_registry)
                if existing_registry is not None
                else self._permission_hook_registry
            )

        from swarmline.compaction import CompactionConfig

        merged_config = dataclasses.replace(
            plan.config,
            compaction=CompactionConfig() if self._compaction_enabled else None,
            evolution_enabled=self._evolution_enabled,
            stuck_detector=self._stuck_detector,
            recovery_cascade=self._recovery_cascade,
        )

        return dataclasses.replace(
            plan,
            config=merged_config,
            active_tools=merged_active_tools,
            create_kwargs=merged_create_kwargs,
        )

    async def run(self, prompt: str) -> AsyncIterator[RuntimeEvent]:
        """Run one turn against the coding runtime, yielding `RuntimeEvent`s.

        Reuses `build_portable_runtime_plan` (coding profile -> canonical
        coding tool surface + scoped policy) and `RuntimeFactoryPort.create`
        to build the runtime, then drives its `run()` async generator. The
        runtime is always cleaned up -- on normal completion, on an
        exception raised while iterating, and via `close()` if the caller
        stops consuming early.

        Session lifecycle (Stage 5): the turn's messages (`self._messages`
        plus the new `prompt`) are built in a LOCAL list and sent to the
        runtime -- `self._messages` itself is only updated once the turn is
        confirmed complete, so an error-only stream, an exception, or the
        caller abandoning consumption early never leaves a half-finished
        turn's prompt sitting in history for the NEXT `run()` call to
        inherit. "Confirmed complete" means a `final` event was observed;
        at that exact point (BEFORE yielding it to the caller -- a caller
        that stops iterating as soon as it sees `final`, a very natural
        pattern, must still get the bump) history is committed, `turn_count`
        bumped, and the session persisted. `final`'s `new_messages` are
        used when present; when empty (a legal shape -- e.g. the thin
        runtime's slash-command intercept yields `final` with no
        `new_messages` at all) a single assistant message is synthesized
        from `final`'s own `text` instead, so a real reply is never silently
        dropped from history.
        """
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan
        from swarmline.runtime.types import Message

        turn_messages = [*self._messages, Message(role="user", content=prompt)]

        plan = build_portable_runtime_plan(
            self._config, "thin", runtime_factory=self._factory
        )
        plan = self._augment_plan(plan)
        runtime = self._factory.create(config=plan.config, **plan.create_kwargs)
        self._active_runtimes[id(runtime)] = runtime
        try:
            async for event in runtime.run(
                messages=turn_messages,
                system_prompt=self._config.system_prompt,
                active_tools=plan.active_tools,
            ):
                if id(runtime) not in self._active_runtimes:
                    # `close()` ran while we were awaiting this event: the
                    # runtime is already cleaned up -- drop the event.
                    break
                if event.type == "final":
                    new_messages = [
                        Message(**payload)
                        for payload in event.data.get("new_messages", [])
                    ]
                    if not new_messages and event.data.get("text"):
                        new_messages = [
                            Message(role="assistant", content=event.data["text"])
                        ]
                    self._messages = turn_messages + new_messages
                    self.turn_count += 1
                    self._status = CodeSessionStatus.RUNNING
                    await self._session_store.save(self._snapshot(), self._messages)
                yield event
                if id(runtime) not in self._active_runtimes:
                    # `close()` ran while we were suspended at `yield`: the
                    # runtime is already cleaned up -- stop consuming it.
                    break
        finally:
            await self._cleanup_runtime(runtime)

    def stream(self, prompt: str) -> AsyncIterator[RuntimeEvent]:
        """Alias for `run` -- same async iterator, kept for API ergonomics."""
        return self.run(prompt)

    async def _cleanup_runtime(self, runtime: Any) -> None:
        """Clean `runtime` exactly once: only the caller that removes it from
        the active registry performs the cleanup; every later path is a no-op."""
        if self._active_runtimes.pop(id(runtime), None) is not None:
            await runtime.cleanup()

    async def close(self) -> None:
        """Release the runtime(s) backing in-flight `run()`/`stream()` calls.

        Idempotent no-op when no run is in flight (either none was started,
        or every run already completed and cleaned itself up via `run`'s own
        `finally`). Exists so a caller that stops consuming the event stream
        early (e.g. breaks out of the `async for` loop) still gets a
        deterministic cleanup point, instead of relying on the async
        generator's eventual garbage collection. Suspended generators notice
        the closure on their next resume and finish without touching the
        already-cleaned runtime.
        """
        for runtime in list(self._active_runtimes.values()):
            await self._cleanup_runtime(runtime)

    def _snapshot(self) -> dict[str, Any]:
        """Build the flat `session.json` payload (see `_session.build_snapshot`).
        `FacadeSessionStore` only knows how to read/write this plain dict --
        it never imports `CodeRuntimeSession` itself."""
        return build_snapshot(
            session_id=self.session_id,
            status=self._status,
            hooks_enabled=self._permission_hook_registry is not None,
            created_at=self._created_at,
            cwd=self._cwd,
            model=self._model,
            turn_count=self.turn_count,
        )

    def session(self) -> CodeRuntimeSession:
        """Return the current session as a `CodeRuntimeSession` value object
        (reused, no new type -- see the plan's Stage 5 reuse table)."""
        return build_code_runtime_session(
            session_id=self.session_id,
            status=self._status,
            hooks_enabled=self._permission_hook_registry is not None,
            created_at=self._created_at,
        )

    async def reset(self) -> None:
        """Clear in-memory history + `turn_count` (keeps `session_id`/`cwd`),
        and persist the cleared state.

        Deletes the old session directory outright rather than reusing
        `_session_store.save`'s incremental append (which would leave the
        old messages on disk, since an empty `messages` list has nothing
        "new" to append against a non-empty existing file).
        """
        self._messages = []
        self.turn_count = 0
        self._status = CodeSessionStatus.CREATED
        await self._session_store.delete(self.session_id)
        await self._session_store.save(self._snapshot(), self._messages)

    @classmethod
    async def resume(
        cls,
        session_id: str,
        *,
        runtime_factory: RuntimeFactoryPort | None = None,
    ) -> CodeAgent:
        """Reconstruct a `CodeAgent` from its persisted session: same
        `cwd`/`model`/`session_id`/history/`turn_count`. Other constructor
        options (tools, `on_permission_request`, resilience knobs, ...) are
        NOT persisted and fall back to their defaults -- only
        `runtime_factory` can be re-supplied, matching the plan's signature.

        Raises:
            FileNotFoundError: no persisted session for `session_id`.
            ValueError: `session.json` exists but is corrupt.
        """
        store = FacadeSessionStore()
        snapshot, messages = await store.load(session_id)

        agent = cls(
            model=snapshot["model"],
            cwd=snapshot["cwd"],
            session_id=session_id,
            runtime_factory=runtime_factory,
        )
        agent._messages = messages
        agent.turn_count = snapshot["turn_count"]
        agent._created_at = datetime.fromisoformat(snapshot["created_at"])
        agent._status = CodeSessionStatus(snapshot["status"])
        return agent
