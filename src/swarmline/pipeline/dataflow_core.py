"""Typed data-flow pipeline — core value types.

The data-flow layer is a deterministic, declarative pipeline substrate: stages are frozen
dataclasses and the engine (:mod:`swarmline.pipeline.dataflow_engine`) dispatches by stage TYPE
through a registry — not an ``isinstance`` chain — so a new stage kind plugs in without editing the
engine (OCP). It is domain-free: handlers, validators and ports are injected, so every stage is
unit-testable offline.

This module holds the value types only (no execution logic): the run context, the per-stage
outcome, the aggregate result, the dependency taxonomy, and the error hierarchy. It imports nothing
from :mod:`swarmline.pipeline`, so the engine, the stage primitives and the legacy
:class:`~swarmline.pipeline.typed.TypedPipeline` facade can all depend on it without a cycle.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Literal

#: A stage's side-effect class. ``pure`` = no I/O (safe to retry); ``io`` = network/disk/budget-
#: bearing; ``llm`` = a model-seam call. Only ``pure`` stages may set ``max_attempts > 1`` —
#: retrying an io/llm stage would re-issue its side effects (double-spend).
StageDependency = Literal["llm", "io", "pure"]

#: Terminal status of a whole data-flow run.
PipelineStatus = Literal["completed", "failed", "fallback"]

#: What to do when a stage raises. ``none`` → the run fails; ``last_valid`` → return the last
#: successful stage output with status ``fallback`` (a graceful, non-crashing degrade).
FallbackMode = Literal["none", "last_valid"]

#: Async event sink: ``await event_sink(event_name, data)``. The engine emits ``status`` (when a
#: stage declares a ``status_label``), ``stage_start``, ``stage_end`` and ``stage_failed``.
EventSink = Callable[[str, "dict[str, Any]"], Awaitable[None]]


class PipelineError(Exception):
    """Base class for all data-flow pipeline errors."""


class StageConfigError(PipelineError):
    """A stage / pipeline is mis-configured (unknown stage type, bad field, illegal retry)."""


class StageValidationError(PipelineError):
    """A stage produced output its validator rejected."""


class StageExecutionError(PipelineError):
    """A stage runner's *fatal* failure that carries its own attempt accounting and a final message.

    A plain exception from a runner fails the pipeline with an engine-formatted error and no attempt
    record. A composite or iterative stage (the bounded review loop, the static fork/join) instead
    needs to fail while reporting how many attempts it made and a message it has already formatted —
    this exception is that contract. The engine records ``attempts`` (plus any ``sub_attempts``) for
    the failing stage and reports ``str(self)`` VERBATIM (no ``"{stage}: "`` prefix).
    """

    def __init__(
        self,
        message: str,
        *,
        attempts: int = 1,
        sub_attempts: Mapping[str, int] | None = None,
        errors: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.sub_attempts = sub_attempts
        #: Per-child NON-fatal error strings surfaced BEFORE the verbatim summary message (e.g. a
        #: fork/join's per-branch failures), so a fatal composite keeps full diagnostic detail.
        self.errors = errors


def resolve_path(obj: Any, path: str) -> Any:
    """Read a dotted ``path`` off ``obj`` — Mapping key or attribute at each hop.

    ``resolve_path(decision, "kind")`` → ``decision.kind`` (object) or ``decision["kind"]`` (dict).
    A missing key/attribute raises :class:`StageConfigError` (routing/selection cannot proceed).
    Shared by the Conditional selector and the FanOut ``over`` resolution.
    """
    current = obj
    for part in path.split("."):
        if isinstance(current, Mapping):
            if part not in current:
                raise StageConfigError(f"path {path!r}: key {part!r} not found")
            current = current[part]
        else:
            try:
                current = getattr(current, part)
            except AttributeError as exc:
                raise StageConfigError(f"path {path!r}: attribute {part!r} not found") from exc
    return current


@dataclasses.dataclass(frozen=True)
class StageOutcome:
    """The result a stage runner returns to the engine.

    ``value`` becomes the next stage's input. ``attempts`` is how many times the handler ran (for
    retry accounting). ``terminate_early`` completes the whole pipeline now, with ``value`` as the
    final output (a first-class graceful success — NOT a failure).

    A composite stage (fork/join, fan-out) may also report ``sub_attempts`` — per-child attempt
    counts (e.g. ``{"compare.fast": 1}``) merged into the run's attempts dict — and ``errors`` —
    NON-fatal child failures surfaced in the result while the run stays ``completed``.
    """

    value: Any
    attempts: int = 1
    terminate_early: bool = False
    sub_attempts: Mapping[str, int] | None = None
    errors: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True)
class PipelineResult:
    """The aggregate outcome of a data-flow run.

    ``status`` is ``completed`` (incl. an early-terminate), ``failed`` (a stage raised, no
    fallback) or ``fallback`` (a stage raised, ``last_valid`` policy returned the last good value).
    ``terminated_early`` flags a guard short-circuit so callers can tell it from a full run.
    """

    status: PipelineStatus
    output: Any = None
    failed_stage: str | None = None
    attempts: dict[str, int] = dataclasses.field(default_factory=dict)
    errors: tuple[str, ...] = ()
    terminated_early: bool = False


@dataclasses.dataclass
class PipelineContext:
    """Mutable per-run side-channel threaded into every stage handler.

    Handlers receive it via the ``(value, context)`` / ``(value, context, params)`` arity and use
    it to publish artifacts (e.g. the per-turn model seam + ports) and compact messages for later
    stages. It is intentionally not a chat bus — just structured carry-through. Real agent-to-agent
    messaging stays in graph/team orchestration.

    This is the single ``PipelineContext`` for the whole pipeline package; the legacy
    :class:`~swarmline.pipeline.typed.TypedPipeline` re-exports it for backward compatibility.
    """

    artifacts: dict[str, Any] = dataclasses.field(default_factory=dict)
    messages: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    metadata: dict[str, Any] = dataclasses.field(default_factory=dict)

    def write_artifact(self, key: str, value: Any) -> None:
        """Store ``value`` under ``key`` for later stages to read."""
        self.artifacts[key] = value

    def read_artifact(self, key: str, default: Any = None) -> Any:
        """Return the artifact under ``key``, or ``default`` when absent."""
        return self.artifacts.get(key, default)

    def add_message(self, sender: str, content: str, **metadata: Any) -> None:
        """Append a compact ``{"from": sender, "content": content, **metadata}`` message."""
        message = {"from": sender, "content": content}
        message.update(metadata)
        self.messages.append(message)
