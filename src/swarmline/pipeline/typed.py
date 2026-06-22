"""Universal typed pipeline facade — the legacy ``TypedPipeline`` surface over the registry engine.

``TypedPipeline`` (alias ``WorkflowChain``) is the original static workflow-chain API. It is now a
THIN facade over the registry-dispatch engine (:func:`swarmline.pipeline.dataflow_engine.run_pipeline`):
it builds an event-name adapter — mapping the engine's events onto the legacy ``event_bus.emit``
names so existing subscribers keep firing — and delegates execution. There is a single engine and a
single set of stage primitives; this module exposes the canonical engine types and serves the
verbose legacy stage names as **deprecated aliases** (no behaviour change, no ``isinstance`` dispatch).

The long ``*PipelineStage`` names are deprecated since 1.6.0 (removal in 2.0.0) and resolve — lazily,
via PEP 562 ``__getattr__``, emitting a ``DeprecationWarning`` — to the canonical short classes:

* ``TypedPipelineStage`` → :class:`~swarmline.pipeline.stages.typed_stage.TypedStage`
* ``ParallelPipelineStage`` → :class:`~swarmline.pipeline.stages.parallel.ParallelStage`
* ``LoopPipelineStage`` → :class:`~swarmline.pipeline.stages.loop.LoopStage`

Each alias returns the *identical* canonical class (never a subclass), so ``type(stage)`` stays
canonical and the engine's type→runner registry still dispatches. ``TypedPipelineResult`` remains a
plain (non-deprecated) alias of :class:`~swarmline.pipeline.dataflow_core.PipelineResult` — the only
public name for the data-flow result class (the top-level ``PipelineResult`` is the distinct
phase-based result), so there is no unambiguous short name to redirect it to.

``PipelineContext`` is the single class from :mod:`swarmline.pipeline.dataflow_core`, re-exported so
``from swarmline.pipeline.typed import PipelineContext`` and the top-level import keep working.
"""

from __future__ import annotations

import dataclasses
import warnings
from typing import Any

from swarmline.pipeline.dataflow_core import (
    EventSink,
    FallbackMode,
    PipelineContext,
    PipelineResult,
)
from swarmline.pipeline.dataflow_engine import run_pipeline
from swarmline.pipeline.stages.loop import LoopStage
from swarmline.pipeline.stages.parallel import ParallelStage
from swarmline.pipeline.stages.typed_stage import TypedStage

# Back-compat re-exports — these module-level type aliases lived in the original ``typed`` engine
# before it became a facade; keep them importable from here (identical ``Literal`` values at their
# new canonical homes) so ``from swarmline.pipeline.typed import PipelineStatus`` keeps working.
from swarmline.pipeline.dataflow_core import PipelineStatus as PipelineStatus
from swarmline.pipeline.stages.parallel import (
    ParallelFailurePolicy as ParallelFailurePolicy,
)


@dataclasses.dataclass(frozen=True)
class FallbackPolicy:
    """Fallback policy for a typed pipeline; ``mode`` is the engine's fallback mode."""

    mode: FallbackMode = "none"


#: Map the registry engine's event names onto the legacy ``TypedPipeline`` event names so existing
#: ``event_bus`` subscribers keep firing. Unmapped names (``branch_*`` / ``loop_iteration_*``) pass
#: through unchanged — they were already the legacy names.
_LEGACY_EVENT_NAMES: dict[str, str] = {
    "stage_start": "pipeline_stage_start",
    "stage_end": "pipeline_stage_end",
    "stage_failed": "pipeline_stage_end",
    "parallel_start": "parallel_stage_start",
    "parallel_join": "parallel_stage_join",
}


class TypedPipeline:
    """Static workflow chain over the registry engine — validators, retries, loops, fork/join, events."""

    def __init__(
        self,
        *,
        stages: list[Any],
        fallback_policy: FallbackPolicy | None = None,
        event_bus: Any | None = None,
    ) -> None:
        if not stages:
            raise ValueError("TypedPipeline requires at least one stage")
        self._stages = list(stages)
        self._fallback_policy = fallback_policy or FallbackPolicy()
        self._bus = event_bus

    async def run(
        self, initial_input: Any, *, context: PipelineContext | None = None
    ) -> PipelineResult:
        """Run all stages sequentially via the registry engine, honouring the fallback policy."""
        return await run_pipeline(
            self._stages,
            initial_input,
            context,
            event_sink=self._event_sink(),
            fallback=self._fallback_policy.mode,
        )

    def _event_sink(self) -> EventSink | None:
        """Adapt the engine's async event sink onto the legacy ``event_bus.emit`` names."""
        bus = self._bus
        if bus is None:
            return None

        async def sink(name: str, data: dict[str, Any]) -> None:
            # The legacy pipeline_stage_end payload carried an ``ok`` flag distinguishing
            # success from failure under the same event name; re-inject it on the adapter.
            if name == "stage_end":
                data = {**data, "ok": True}
            elif name == "stage_failed":
                data = {**data, "ok": False}
            await bus.emit(_LEGACY_EVENT_NAMES.get(name, name), data)

        return sink


# ── Backward-compatible aliases — the canonical engine types under their legacy names ────────────
# ``TypedPipelineResult`` is a plain (non-deprecated) alias: it is the only public name for the
# data-flow result class. ``WorkflowChain``/``WorkflowStep``/``WorkflowChainResult`` are the original
# workflow-chain surface and stay non-deprecated. The verbose ``*PipelineStage`` names are deprecated
# and served lazily below (see ``__getattr__``).
TypedPipelineResult = PipelineResult
PipelineStage = TypedStage | ParallelStage | LoopStage

WorkflowChain = TypedPipeline
WorkflowStep = TypedStage
WorkflowChainResult = PipelineResult


# ── Deprecated long aliases (PEP 562) ────────────────────────────────────────────────────────────
#: Long legacy stage name → (canonical short name, canonical class). Returning the canonical class —
#: not a subclass — keeps ``type(stage)`` canonical so the engine's type→runner registry dispatches.
_DEPRECATED_STAGE_ALIASES: dict[str, tuple[str, type]] = {
    "TypedPipelineStage": ("TypedStage", TypedStage),
    "ParallelPipelineStage": ("ParallelStage", ParallelStage),
    "LoopPipelineStage": ("LoopStage", LoopStage),
}


#: Aliases already warned about this process — collapses the duplicate fire that CPython's
#: ``from pkg import Name`` machinery (``_handle_fromlist`` probes ``__getattr__`` twice) produces, so
#: each deprecated alias warns at most once per process. Cleared between tests by an autouse fixture.
_warned_aliases: set[str] = set()


def _warn_deprecated_alias(name: str) -> type:
    """Warn once-per-process for a deprecated long alias and return its canonical class.

    Precondition: ``name in _DEPRECATED_STAGE_ALIASES``. Called from this module's and the package's
    ``__getattr__`` at equal depth (user → ``__getattr__`` → here → ``warn``), so ``stacklevel=3``
    lands on user code from either import path.
    """
    canonical_name, canonical = _DEPRECATED_STAGE_ALIASES[name]
    if name not in _warned_aliases:
        _warned_aliases.add(name)
        warnings.warn(
            f"{name} is deprecated since swarmline 1.6.0; import {canonical_name} instead "
            "(it will be removed in 2.0.0).",
            DeprecationWarning,
            stacklevel=3,
        )
    return canonical


def __getattr__(name: str) -> Any:
    """PEP 562 — serve the deprecated long stage aliases lazily so importing the module stays clean."""
    if name in _DEPRECATED_STAGE_ALIASES:
        return _warn_deprecated_alias(name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
