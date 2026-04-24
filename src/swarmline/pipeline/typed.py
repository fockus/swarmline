"""Universal typed pipeline primitives.

This module intentionally contains no domain concepts. It provides a small
workflow chain that applications can compose into generation, validation,
evaluation, review-loop, and fork/join flows.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

FallbackMode = Literal["none", "last_valid"]
PipelineStatus = Literal["completed", "failed", "fallback"]
ParallelFailurePolicy = Literal["require_all", "allow_partial"]


@dataclass(frozen=True)
class FallbackPolicy:
    """Fallback policy for typed pipeline failures."""

    mode: FallbackMode = "none"


@dataclass
class PipelineContext:
    """Shared structured context for a workflow chain run.

    It is intentionally not a chat bus. Stages can publish artifacts and compact
    messages for later join/review stages, while real agent-to-agent messaging
    remains in graph/team orchestration.
    """

    artifacts: dict[str, Any] = field(default_factory=dict)
    messages: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def write_artifact(self, key: str, value: Any) -> None:
        """Store a structured artifact for later stages."""
        self.artifacts[key] = value

    def read_artifact(self, key: str, default: Any = None) -> Any:
        """Read a structured artifact."""
        return self.artifacts.get(key, default)

    def add_message(self, sender: str, content: str, **metadata: Any) -> None:
        """Record a compact pipeline-local message."""
        message = {"from": sender, "content": content}
        message.update(metadata)
        self.messages.append(message)


@dataclass(frozen=True)
class TypedPipelineStage:
    """One sequential pipeline stage."""

    name: str
    handler: Callable[..., Any | Awaitable[Any]]
    validator: Callable[..., bool | None | Awaitable[bool | None]] | None = None
    max_attempts: int = 1

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("stage name must not be empty")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")


@dataclass(frozen=True)
class ParallelPipelineStage:
    """Static fork/join stage for a workflow chain."""

    name: str
    branches: Mapping[str, TypedPipelineStage]
    joiner: Callable[..., Any | Awaitable[Any]] | None = None
    failure_policy: ParallelFailurePolicy = "require_all"

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("parallel stage name must not be empty")
        if not self.branches:
            raise ValueError("parallel stage requires at least one branch")
        if self.failure_policy not in {"require_all", "allow_partial"}:
            raise ValueError("failure_policy must be 'require_all' or 'allow_partial'")


@dataclass(frozen=True)
class LoopPipelineStage:
    """Bounded review loop stage.

    The body runs, then reviewer decides whether the output can continue.
    If reviewer returns False, the body is retried against the original stage
    input until max_iterations is reached. Stages that need reviewer notes can
    use PipelineContext artifacts/messages.
    """

    name: str
    body: TypedPipelineStage
    reviewer: Callable[..., bool | Awaitable[bool]]
    max_iterations: int = 3

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("loop stage name must not be empty")
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be >= 1")


PipelineStage = TypedPipelineStage | ParallelPipelineStage | LoopPipelineStage


@dataclass(frozen=True)
class TypedPipelineResult:
    """Result of a typed pipeline run."""

    status: PipelineStatus
    output: Any = None
    failed_stage: str | None = None
    attempts: dict[str, int] = field(default_factory=dict)
    errors: tuple[str, ...] = ()


class TypedPipeline:
    """Static workflow chain with validators, retries, loops, fork/join, and events."""

    def __init__(
        self,
        *,
        stages: list[PipelineStage],
        fallback_policy: FallbackPolicy | None = None,
        event_bus: Any | None = None,
    ) -> None:
        if not stages:
            raise ValueError("TypedPipeline requires at least one stage")
        self._stages = list(stages)
        self._fallback_policy = fallback_policy or FallbackPolicy()
        self._bus = event_bus

    async def run(
        self,
        initial_input: Any,
        *,
        context: PipelineContext | None = None,
    ) -> TypedPipelineResult:
        """Run all stages sequentially."""
        current = initial_input
        run_context = context or PipelineContext()
        last_valid: Any = None
        has_last_valid = False
        attempts_by_stage: dict[str, int] = {}
        errors: list[str] = []

        for stage in self._stages:
            await self._emit("pipeline_stage_start", {"stage": stage.name})
            stage_result, stage_attempts, stage_errors, error = await self._run_any_stage(
                stage,
                current,
                run_context,
            )
            attempts_by_stage.update(stage_attempts)
            errors.extend(stage_errors)
            if error is not None:
                errors.append(error)
                await self._emit(
                    "pipeline_stage_end",
                    {"stage": stage.name, "ok": False, "error": error},
                )
                if self._fallback_policy.mode == "last_valid" and has_last_valid:
                    await self._emit(
                        "fallback_selected",
                        {"stage": stage.name, "mode": "last_valid"},
                    )
                    return TypedPipelineResult(
                        status="fallback",
                        output=last_valid,
                        failed_stage=stage.name,
                        attempts=attempts_by_stage,
                        errors=tuple(errors),
                    )
                return TypedPipelineResult(
                    status="failed",
                    output=None,
                    failed_stage=stage.name,
                    attempts=attempts_by_stage,
                    errors=tuple(errors),
                )

            current = stage_result
            last_valid = stage_result
            has_last_valid = True
            await self._emit("pipeline_stage_end", {"stage": stage.name, "ok": True})

        return TypedPipelineResult(
            status="completed",
            output=current,
            attempts=attempts_by_stage,
            errors=tuple(errors),
        )

    async def _run_any_stage(
        self,
        stage: PipelineStage,
        current: Any,
        context: PipelineContext,
    ) -> tuple[Any, dict[str, int], list[str], str | None]:
        if isinstance(stage, ParallelPipelineStage):
            output, branch_attempts, errors, error = await self._run_parallel_stage(
                stage,
                current,
                context,
            )
            return output, branch_attempts, errors, error
        if isinstance(stage, LoopPipelineStage):
            output, loop_attempts, error = await self._run_loop_stage(stage, current, context)
            return output, {stage.name: loop_attempts}, [], error
        output, stage_attempts, error = await self._run_stage(stage, current, context)
        return output, {stage.name: stage_attempts}, [], error

    async def _run_stage(
        self,
        stage: TypedPipelineStage,
        current: Any,
        context: PipelineContext,
    ) -> tuple[Any, int, str | None]:
        last_error: str | None = None
        for attempt in range(1, stage.max_attempts + 1):
            try:
                output = await _call_with_optional_context(stage.handler, current, context)
                await self._validate(stage, output, context)
                return output, attempt, None
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
        return None, stage.max_attempts, last_error or "stage failed"

    async def _run_parallel_stage(
        self,
        stage: ParallelPipelineStage,
        current: Any,
        context: PipelineContext,
    ) -> tuple[Any, dict[str, int], list[str], str | None]:
        await self._emit("parallel_stage_start", {"stage": stage.name})

        async def _run_branch(branch_name: str, branch: TypedPipelineStage) -> tuple[str, Any, int, str | None]:
            await self._emit("branch_start", {"stage": stage.name, "branch": branch_name})
            output, attempts, error = await self._run_stage(branch, current, context)
            await self._emit(
                "branch_end",
                {
                    "stage": stage.name,
                    "branch": branch_name,
                    "ok": error is None,
                    "error": error,
                },
            )
            return branch_name, output, attempts, error

        branch_results = await asyncio.gather(
            *[
                _run_branch(branch_name, branch)
                for branch_name, branch in stage.branches.items()
            ]
        )

        outputs: dict[str, Any] = {}
        attempts: dict[str, int] = {}
        errors: list[str] = []
        for branch_name, output, attempt_count, error in branch_results:
            attempts[f"{stage.name}.{branch_name}"] = attempt_count
            if error is None:
                outputs[branch_name] = output
            else:
                errors.append(f"{stage.name}.{branch_name}: {error}")

        if errors and stage.failure_policy == "require_all":
            return None, attempts | {stage.name: 1}, errors, "; ".join(errors)
        if not outputs:
            return None, attempts | {stage.name: 1}, errors, "all parallel branches failed"

        if stage.joiner is None:
            joined = outputs
        else:
            joined = await _call_with_optional_context(stage.joiner, outputs, context)
        await self._emit(
            "parallel_stage_join",
            {
                "stage": stage.name,
                "branches": tuple(outputs),
                "partial": bool(errors),
            },
        )
        return joined, attempts | {stage.name: 1}, errors, None

    async def _run_loop_stage(
        self,
        stage: LoopPipelineStage,
        current: Any,
        context: PipelineContext,
    ) -> tuple[Any, int, str | None]:
        for iteration in range(1, stage.max_iterations + 1):
            await self._emit("loop_iteration_start", {"stage": stage.name, "iteration": iteration})
            candidate, _attempts, error = await self._run_stage(stage.body, current, context)
            if error is not None:
                return None, iteration, error
            approved = await _call_with_optional_context(stage.reviewer, candidate, context)
            await self._emit(
                "loop_iteration_end",
                {
                    "stage": stage.name,
                    "iteration": iteration,
                    "approved": bool(approved),
                },
            )
            if approved:
                return candidate, iteration, None
        return (
            None,
            stage.max_iterations,
            f"stage '{stage.name}' reviewer did not pass after {stage.max_iterations} iterations",
        )

    async def _validate(
        self,
        stage: TypedPipelineStage,
        output: Any,
        context: PipelineContext,
    ) -> None:
        if stage.validator is None:
            return
        result = await _call_with_optional_context(stage.validator, output, context)
        if result is False:
            raise ValueError(f"stage '{stage.name}' validator returned False")

    async def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        if self._bus is not None:
            await self._bus.emit(event_type, data)


async def _maybe_await(value: Any | Awaitable[Any]) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _call_with_optional_context(
    fn: Callable[..., Any | Awaitable[Any]],
    value: Any,
    context: PipelineContext,
) -> Any:
    if _accepts_context(fn):
        return await _maybe_await(fn(value, context))
    return await _maybe_await(fn(value))


def _accepts_context(fn: Callable[..., Any]) -> bool:
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        return False
    positional_count = 0
    for parameter in signature.parameters.values():
        if parameter.kind == inspect.Parameter.VAR_POSITIONAL:
            return True
        if parameter.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            positional_count += 1
    return positional_count >= 2


WorkflowChain = TypedPipeline
WorkflowStep = TypedPipelineStage
WorkflowChainResult = TypedPipelineResult
