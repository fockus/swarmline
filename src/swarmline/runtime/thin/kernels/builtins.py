"""Built-in ExecutionKernel adapters and auto-registration helper.

Each adapter wraps one of the three existing loop-strategy functions
(run_react / run_planner / run_conversational) and normalises their
heterogeneous positional signatures into a single ``run(ctx: KernelContext)``
call — pure signature adaptation, zero logic change.

REQ-002: single KernelContext input for every kernel — mode-specific inputs
(e.g. ``session_dispatcher``) are read from ``ctx``, never passed as
factory/constructor kwargs.
REQ-009: built-in react / planner / conversational kernels preserved byte-for-byte.

kernel-patterns spec, Task 2 (REQ-001, REQ-005, REQ-006): ``PlanExecuteKernel``
formalizes the static plan-and-execute pattern (= ``run_planner``) as a
first-class named kernel, registered under BOTH the pre-existing ``planner``
mode and the new ``plan-execute`` mode. ``PlannerKernelAdapter`` is kept as a
backward-compat alias of the SAME class — one implementation, zero duplicated
plan/execute logic (DRY).

kernel-patterns spec, Task 3 (REQ-002, REQ-007, REQ-008): ``ADaPTKernel``
(module ``kernels/adapt.py``, kept out of this file to stay thin) adds
adaptive, decompose-ON-FAILURE execution — registered under mode ``adapt``.

kernel-patterns spec, Task 6 (REQ-005, REQ-012, REQ-013): registers the two
remaining kernels — ``sgr`` (``SGRKernel``, module ``kernels/sgr.py``, kept
out of this file to stay thin) and ``reflection`` (``ReflectionKernelAdapter``,
below). ``ReflectionKernelAdapter`` is the one adapter here that does NOT
just forward ``ctx`` unchanged: ``ReflectionKernel`` (``kernels/reflection.py``,
UNCHANGED by this task) requires an ``ExternalSignal`` at CONSTRUCTION
(REQ-009), while the registry only builds kernels via zero-argument factories
(REQ-002/REQ-004) — so this adapter reads the signal PER-RUN from
``ctx.external_signal`` and either delegates to a freshly-constructed
``ReflectionKernel(signal)`` or, when no signal was configured, surfaces a
single terminal ``dependency_missing`` error (REQ-009: never a silent
no-op/always-pass default signal). Tree-search kernels (ToT/LATS/RAP) remain
OUT OF SCOPE for this spec — deferred, backlog I-002.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from swarmline.domain_types import RuntimeErrorData, RuntimeEvent
from swarmline.runtime.thin.kernels.adapt import ADaPTKernel
from swarmline.runtime.thin.kernels.reflection import ReflectionKernel
from swarmline.runtime.thin.strategies import (
    run_conversational,
    run_planner,
    run_react,
)

# NOTE: SGRKernel is NOT imported at module scope here.  ``kernels/sgr.py``
# imports ``swarmline.orchestration.nextstep``, whose package ``__init__``
# transitively imports ``swarmline.runtime.thin.runtime`` (ThinTeamOrchestrator
# -> ThinSubagentOrchestrator -> ThinRuntime) — the very module that, in the
# common case of ``ThinRuntime`` being the first thing imported in a process,
# is ITSELF still mid-import when it reaches its own
# ``from swarmline.runtime.thin.kernels import get_default_kernel_registry``
# line.  Even a function-scoped import at ``_register_builtins`` call time is
# too early (that function runs as part of the registry's import-time
# self-init) — see ``_sgr_factory`` below, where the import is deferred all
# the way to the first actual ``registry.get("sgr")`` call.

if TYPE_CHECKING:
    from swarmline.types import KernelContext


class ConversationalKernelAdapter:
    """Wraps run_conversational.

    Intentionally ignores ``ctx.executor``, ``ctx.tools``, and
    ``ctx.native_adapter`` — run_conversational has no such parameters.
    """

    def run(self, ctx: KernelContext) -> AsyncIterator[RuntimeEvent]:
        """Unpack *ctx* into run_conversational's positional/keyword args."""
        return run_conversational(
            ctx.llm_call,
            ctx.messages,
            ctx.system_prompt,
            ctx.config,
            ctx.start_time,
            checkpoint=ctx.checkpoint,
            on_retry=ctx.on_retry,
        )


class PlanExecuteKernel:
    """Formalizes the static plan-and-execute pattern: generate a plan once,
    then execute its steps in order (REQ-001). Wraps ``run_planner`` — pure
    signature adaptation, zero logic duplication.

    Registered under both ``plan-execute`` (canonical mode) and ``planner``
    (pre-existing, backward-compat) — same kernel, two mode names.
    """

    def run(self, ctx: KernelContext) -> AsyncIterator[RuntimeEvent]:
        """Unpack *ctx* into run_planner's positional/keyword args."""
        if ctx.executor is None:
            raise ValueError("PlanExecuteKernel requires ctx.executor (not None)")
        return run_planner(
            ctx.llm_call,
            ctx.executor,
            ctx.messages,
            ctx.system_prompt,
            ctx.tools or [],
            ctx.config,
            ctx.start_time,
            checkpoint=ctx.checkpoint,
        )


# Backward-compat alias (H1 golden tests + external callers import this name).
# Same class, not a copy — DRY: one plan/execute implementation.
PlannerKernelAdapter = PlanExecuteKernel


class ReactKernelAdapter:
    """Wraps run_react.

    ``session_dispatcher`` is read from ``ctx.session_dispatcher`` (REQ-002:
    KernelContext is the single normalized input for every kernel — no
    mode-specific constructor kwargs) and forwarded to ``run_react`` so that
    session events (e.g. ``file.edited``) continue to fire during the react
    loop.
    """

    def run(self, ctx: KernelContext) -> AsyncIterator[RuntimeEvent]:
        """Unpack *ctx* into run_react's positional/keyword args."""
        if ctx.executor is None:
            raise ValueError("ReactKernelAdapter requires ctx.executor (not None)")
        # Sprint 1ce CE-9: forwarded only when set, so the default call to
        # run_react stays exactly what it was before the refresher existed.
        round_kwargs: dict[str, Any] = (
            {"round_refresher": ctx.round_refresher}
            if ctx.round_refresher is not None
            else {}
        )
        return run_react(
            ctx.llm_call,
            ctx.executor,
            ctx.messages,
            ctx.system_prompt,
            ctx.tools or [],
            ctx.config,
            ctx.start_time,
            checkpoint=ctx.checkpoint,
            on_retry=ctx.on_retry,
            native_adapter=ctx.native_adapter,
            session_dispatcher=ctx.session_dispatcher,
            **round_kwargs,
        )


class ReflectionKernelAdapter:
    """Adapts ReflectionKernel's construction-time-required ExternalSignal
    (REQ-009) to the registry's zero-argument factory contract (REQ-002/004).

    ``ReflectionKernel`` itself is UNCHANGED by this task — its constructor
    still rejects ``signal=None`` (REQ-009 at construction, for direct
    callers that build it themselves). This adapter instead reads the signal
    PER-RUN from ``ctx.external_signal`` (REQ-002: KernelContext is the
    single normalized input every kernel reads from, never a mode-specific
    registry kwarg) and either delegates to a freshly-constructed
    ``ReflectionKernel(signal)`` — forwarding its stream untouched — or, when
    no signal was configured, surfaces a single terminal
    ``dependency_missing`` error. This is REQ-009's "no silent no-op/always-
    pass signal" guarantee extended to the registry path: an unset
    ``config.external_signal`` must never silently make ``mode="reflection"``
    behave like plain generation with an ever-passing critic.
    """

    def run(self, ctx: KernelContext) -> AsyncIterator[RuntimeEvent]:
        """Delegate to a real ReflectionKernel built from ctx.external_signal."""
        signal = ctx.external_signal
        if signal is None:
            return self._missing_signal_error()
        return ReflectionKernel(signal).run(ctx)

    @staticmethod
    async def _missing_signal_error() -> AsyncIterator[RuntimeEvent]:
        """Single terminal error — REQ-009: no silent no-op signal, ever."""
        yield RuntimeEvent.error(
            RuntimeErrorData(
                kind="dependency_missing",
                message=(
                    "reflection mode requires config.external_signal "
                    "(ExternalSignal); none was configured"
                ),
                recoverable=False,
            )
        )


# ---------------------------------------------------------------------------
# Auto-registration helper
# ---------------------------------------------------------------------------


def _register_builtins(registry: Any) -> None:
    """Register the built-in kernel factories into *registry*.

    Factories are zero-argument callables (REQ-002/REQ-004): every input a
    kernel needs is read from the ``KernelContext`` passed to ``run(ctx)``,
    never from factory/constructor kwargs.

    ``plan-execute`` and ``planner`` both resolve to ``PlanExecuteKernel``
    (REQ-005 additive registration, REQ-012 backward-compat: ``planner``
    keeps behaving identically to before this task).

    ``adapt`` resolves to ``ADaPTKernel`` with its default ``max_depth=3``
    (kernel-patterns spec, Task 3, REQ-002/REQ-005: additive, selected only
    on explicit ``mode_hint="adapt"``).

    ``reflection`` resolves to ``ReflectionKernelAdapter`` (Task 6): the
    adapter reads ``ctx.external_signal`` per-run rather than taking a
    constructor kwarg, since the registry only builds zero-argument
    factories. ``sgr`` resolves to ``SGRKernel`` with its default
    ``max_steps=8`` (Task 6): the class itself is zero-argument
    constructible, so no adapter wrapper is needed.

    ``SGRKernel``'s import is deferred all the way into ``_sgr_factory``
    below — NOT even at ``_register_builtins`` call time (unlike every other
    factory here) — because ``_register_builtins`` itself runs as part of
    the default registry's self-init, which fires from
    ``kernels/__init__.py`` at IMPORT time.  ``kernels/sgr.py`` imports
    ``swarmline.orchestration.nextstep``, whose package ``__init__``
    transitively imports ``swarmline.runtime.thin.runtime`` (ThinTeamOrchestrator
    -> ThinSubagentOrchestrator -> ThinRuntime) — the very module that (in the
    common case of ``ThinRuntime`` being the first thing imported in a
    process) is ITSELF still mid-import when it reaches its own
    ``from swarmline.runtime.thin.kernels import get_default_kernel_registry``
    line.  Importing ``kernels/sgr.py`` any earlier than the FIRST actual
    ``registry.get("sgr")`` call (i.e. the first real dispatch to SGR mode,
    long after all module-level imports across the process have finished)
    reliably cycles back into that partially-initialized ``runtime.py``.
    """
    registry.register(
        "conversational",
        lambda: ConversationalKernelAdapter(),
    )
    registry.register(
        "planner",
        lambda: PlanExecuteKernel(),
    )
    registry.register(
        "plan-execute",
        lambda: PlanExecuteKernel(),
    )
    registry.register(
        "react",
        lambda: ReactKernelAdapter(),
    )
    registry.register(
        "adapt",
        lambda: ADaPTKernel(),
    )
    registry.register(
        "reflection",
        lambda: ReflectionKernelAdapter(),
    )
    registry.register("sgr", _sgr_factory)


def _sgr_factory() -> Any:
    """Build an ``SGRKernel`` — import deferred to first-call time.

    See the "SGRKernel's import is deferred" paragraph in
    ``_register_builtins``'s docstring above for why this cannot be a plain
    ``lambda: SGRKernel()`` with the import at module or ``_register_builtins``
    call scope like every other factory here.
    """
    from swarmline.runtime.thin.kernels.sgr import SGRKernel

    return SGRKernel()
