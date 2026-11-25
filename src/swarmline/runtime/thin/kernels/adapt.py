"""ADaPTKernel — decompose-on-failure, depth-bounded execution kernel.

kernel-patterns spec, Task 3 (REQ-002, REQ-007, REQ-008), Scenario 1.
ADR "ADaPT вместо статичного плана" (design.md, arxiv 2311.05772): unlike
the static ``PlanExecuteKernel`` (plan once, execute steps blindly),
``ADaPTKernel`` only decomposes a step INTO ordered sub-steps when that
step's DIRECT execution (inner ReAct — ``run_react``) fails.  A step that
succeeds directly is never decomposed (simple path, zero extra LLM calls).
Decomposition depth is bounded by ``max_depth``: once the bound is reached,
ADaPT stops decomposing and surfaces a terminal failure for that step
instead of recursing further (REQ-008).

Failure signal (REQ-007, the deterministic + testable part): ``run_react``
and ``finalization.finalize_with_validation`` end their stream with EXACTLY
ONE terminal ``RuntimeEvent`` on every path exercised by this module — a
single event of type ``"final"`` on success, or type ``"error"`` on failure
(loop-limit / bad-model-output / budget-exceeded / cancelled / tool-or-LLM
error), immediately followed by ``return`` at every failure site — see e.g.
``react_strategy.py``'s ``# Loop limit reached`` guard at the end of the
while-loop (``yield RuntimeEvent.error(RuntimeErrorData(kind="loop_limit",
...))``) and the ``bad_model_output`` / ``budget_exceeded`` sites earlier in
the same loop, plus ``finalization.py::finalize_with_validation``'s own
terminal ``final``/``error`` yields on the structured-output path.  ADaPT
drives its decompose decision directly off this terminal event's
``.is_final`` / ``.is_error`` — no new protocol field, no bespoke parsing
of run_react's internals.  A terminal ``error`` is decomposed ONLY when its
``kind`` is in the ALLOW-LIST ``_DECOMPOSABLE_ERROR_KINDS`` — a per-step
reasoning failure with a HEALTHY runtime (``loop_limit``: the agent loop
exhausted its iteration budget without converging; ``bad_model_output``: the
model's response didn't parse) where retrying via smaller sub-steps may
genuinely help.  EVERY OTHER kind — including ``cancelled``,
``budget_exceeded``, ``runtime_crash``, ``dependency_missing``,
``capability_unsupported``, ``guardrail_tripwire``, ``mcp_timeout``, and any
future/unknown kind — is a GLOBAL/runtime failure and is PROPAGATED as-is
instead of driving a decompose retry (fail-safe default: an unrecognized
kind propagates rather than risk silently masking a provider/runtime crash
as an ordinary "step that needs decomposing").  Decomposing a cancelled run
would keep it "working" after cancellation; decomposing a budget-exceeded
run would spend MORE tokens on top of an already-exhausted budget;
decomposing on top of a ``runtime_crash`` would spend a decompose call
trying to "fix" a healthy step whose provider just crashed, silently
masking the crash as an ordinary step failure (GPT-5.5 review round 2,
MAJOR 1 — the previous DENY-list, which propagated only ``cancelled`` /
``budget_exceeded``, treated ``runtime_crash`` and every other kind as
decomposable by default, which is unsafe).

NOT exactly-one in one opt-in, dead-by-default corner: the self-evolution
"stuck escalation" path (requires ``config.evolution_enabled`` PLUS both
``config.stuck_detector`` and ``config.recovery_cascade`` set — none of
which ADaPT or its callers enable) can ``return`` after only a ``status``
event and NO terminal ``final``/``error`` at all — see
``react_strategy.py:616-620``
(``if not recovery.should_continue: yield RuntimeEvent.status(...); return``).
ADaPT does not special-case this: a step whose inner ``run_react`` stream
ends without ever setting the local ``ok`` flag is treated as a failed
attempt — "no terminal seen" is failure, decomposed/bounded exactly like a
genuine terminal error, never a silent success.

Decompose mechanism (REQ-007): ONE ``ctx.llm_call``, reusing the SAME
plan-generation/parse pair ``run_planner`` uses — ``build_planner_prompt``
(prompt) + ``parse_plan`` (response -> ordered ``PlanSchema.steps``) — from
``swarmline.runtime.thin.prompts`` / ``parsers`` — applied here to a single
failed step instead of the whole task.  Sub-steps then run in order via
recursive ADaPT calls at ``depth + 1`` (each sub-step gets its own direct
attempt first, and can itself be decomposed on failure).

Depth bound (REQ-008): ``depth + 1 > max_depth`` is checked BEFORE
decomposing; when true, ADaPT stops (no decompose call, no further
recursion) and yields exactly one failure ``RuntimeEvent.error`` naming the
step and the bound reached.

Event-forwarding invariant (by construction, provable by structural
induction over ``_run_step``): every call forwards zero or more progress
events (status / tool_call_started / tool_call_finished / assistant_delta /
thinking_delta) and yields EXACTLY ONE terminal event — a single ``final``
on success or a single ``error`` on failure.  Nested terminal events (a
failed direct attempt that then gets decomposed successfully, or a
successful non-last sub-step) are internal control-flow signals and are
deliberately NOT forwarded to the caller — only the terminal event that
closes the CURRENT call's own outcome is (this includes a propagated
global error, which IS the current call's terminal event).
"""

from __future__ import annotations

import dataclasses
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from swarmline.runtime.thin.errors import ThinLlmError
from swarmline.runtime.thin.helpers import _messages_to_lm
from swarmline.runtime.thin.parsers import parse_plan
from swarmline.runtime.thin.prompts import build_plan_step_prompt, build_planner_prompt
from swarmline.runtime.thin.react_strategy import run_react
from swarmline.runtime.thin.schemas import PlanStep
from swarmline.runtime.types import RuntimeErrorData, RuntimeEvent

if TYPE_CHECKING:
    from swarmline.types import KernelContext

# MAJOR 1 (GPT-5.5 review round 2, VERIFY-gate safety fix): ALLOW-LIST of
# decomposable step failures — a per-step reasoning failure with a HEALTHY
# runtime, where decomposing into smaller sub-steps may genuinely help.
# Everything else (cancelled, budget_exceeded, runtime_crash,
# dependency_missing, capability_unsupported, guardrail_tripwire,
# mcp_timeout, and any unknown/future kind) is a global/runtime failure that
# PROPAGATES instead — fail-safe for unknown kinds, so a new error kind
# added later is never silently treated as decomposable. The previous
# DENY-list (propagate only cancelled/budget_exceeded, decompose everything
# else BY DEFAULT) was unsafe: a provider ``runtime_crash`` would spend a
# decompose call trying to "fix" a healthy step whose provider just crashed,
# masking the crash as an ordinary step failure. RuntimeErrorData.recoverable
# is always False across this codebase (see react_strategy.py /
# finalization.py / runtime_support.py) so it cannot distinguish "retry via
# decompose" from "stop now" — kind is the only signal that does, so we key
# off it directly.
_DECOMPOSABLE_ERROR_KINDS: frozenset[str] = frozenset(
    {"loop_limit", "bad_model_output"}
)


class ADaPTKernel:
    """Adaptive decompose-on-failure kernel (REQ-002).

    ``max_depth`` bounds recursive decomposition (REQ-008). It is a
    constructor argument, not a ``KernelContext`` field: per-run inputs
    (messages, tools, executor, ...) still flow entirely through ``ctx``
    (REQ-002), while ``max_depth`` configures the KERNEL instance itself —
    the same pattern the registry factory uses (``lambda: ADaPTKernel()``,
    default ``max_depth=3``).
    """

    def __init__(self, max_depth: int = 3) -> None:
        self._max_depth = max_depth

    def run(self, ctx: KernelContext) -> AsyncIterator[RuntimeEvent]:
        """Execute the task as the depth-0 ADaPT step."""
        if ctx.executor is None:
            raise ValueError("ADaPTKernel requires ctx.executor (not None)")
        return self._run_step(ctx, depth=0, title="task")

    async def _run_step(
        self, ctx: KernelContext, depth: int, title: str
    ) -> AsyncIterator[RuntimeEvent]:
        """Run one ADaPT step: direct ReAct execution first; decompose and
        retry only on failure, bounded by ``max_depth`` (REQ-007/REQ-008).
        """
        assert ctx.executor is not None  # guaranteed by run() before recursion starts
        ok = False
        async for event in run_react(
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
        ):
            if event.is_final:
                ok = True
                yield event
            elif event.is_error:
                if event.data.get("kind") not in _DECOMPOSABLE_ERROR_KINDS:
                    # MAJOR 1 safety fix (allow-list, fail-safe for unknown
                    # kinds): anything NOT in the decomposable allow-list —
                    # cancelled, budget_exceeded, runtime_crash,
                    # dependency_missing, capability_unsupported,
                    # guardrail_tripwire, mcp_timeout, or any future/unknown
                    # kind — is a global/runtime failure and must be
                    # forwarded AS-IS. Decomposing it would trigger ANOTHER
                    # ctx.llm_call: keeping a cancelled run "working",
                    # spending more tokens on top of an exhausted budget, or
                    # masking a provider crash as an ordinary step failure.
                    yield event
                    return
                # A decomposable failure (loop_limit / bad_model_output — the
                # runtime is healthy, the step's own reasoning/loop just
                # didn't converge) is an internal signal only — it drives
                # the decompose decision below, never leaked as-is (REQ-007:
                # only a genuinely unrecoverable failure, at the depth
                # bound, is surfaced to the caller).
                pass
            else:
                yield event

        if ok:
            return  # simple path: direct success, no decomposition (REQ-002)

        # --- Direct execution failed: decompose, unless the bound is hit ---
        if depth + 1 > self._max_depth:
            yield RuntimeEvent.error(
                RuntimeErrorData(
                    kind="loop_limit",
                    message=(
                        f"ADaPT: step {title!r} failed and max_depth "
                        f"({self._max_depth}) was reached; stopping "
                        "decomposition."
                    ),
                    recoverable=False,
                )
            )
            return

        yield RuntimeEvent.status(
            f"ADaPT: step {title!r} failed — decomposing "
            f"(depth {depth + 1}/{self._max_depth})"
        )

        sub_steps, decompose_error = await self._decompose(ctx, title)
        if decompose_error is not None:
            yield decompose_error
            return

        # --- Sub-step execution: siblings are chained via step_results /
        # step_context — mirrors run_planner's pattern (planner_strategy.py:
        # 95, 104-106, 172 — accumulate each step's result text, thread it
        # into the next step's context via build_plan_step_prompt) so
        # sub-step N actually sees sub-step N-1's outcome (MAJOR 2 fix; DRY,
        # no new formatter).  Each sub-step's own ``new_messages`` is also
        # accumulated, in order, so the terminal ``final`` this call
        # forwards carries the FULL conversation history generated across
        # every executed sub-step — not just the last one's local messages
        # (MAJOR 3 fix; matches the already-serialized dict shape
        # ``finalization._make_final_event`` / ``RuntimeEvent.final`` build,
        # which is exactly what ``agent/conversation.py`` expects to extend
        # ``self._history`` with).
        last_idx = len(sub_steps) - 1
        step_results: list[str] = []
        accumulated_new_messages: list[dict[str, Any]] = []
        for idx, step in enumerate(sub_steps):
            step_context = (
                "\n".join(step_results) if step_results else f"Parent step: {title}"
            )
            sub_ctx = dataclasses.replace(
                ctx,
                system_prompt=build_plan_step_prompt(
                    ctx.system_prompt,
                    step.title,
                    step_context,
                    ctx.tools or [],
                ),
            )
            sub_step_text = ""
            async for event in self._run_step(sub_ctx, depth + 1, step.title):
                if event.is_error:
                    # Ordered, fail-fast: stop remaining sub-steps and
                    # propagate this step's failure to the caller (REQ-007).
                    yield event
                    return
                if event.is_final:
                    sub_step_text = event.data.get("text", "")
                    accumulated_new_messages = [
                        *accumulated_new_messages,
                        *event.data.get("new_messages", []),
                    ]
                    if idx != last_idx:
                        continue  # intermediate sub-step done; not our terminal event
                    # This IS the current call's terminal event: patch in the
                    # FULL accumulated history before forwarding it.
                    event = dataclasses.replace(
                        event,
                        data={**event.data, "new_messages": accumulated_new_messages},
                    )
                yield event
            step_results.append(sub_step_text)

    async def _decompose(
        self, ctx: KernelContext, title: str
    ) -> tuple[list[PlanStep], RuntimeEvent | None]:
        """One ``ctx.llm_call`` breaking *title* into ordered sub-steps.

        Reuses ``build_planner_prompt`` + ``parse_plan`` — the SAME
        plan-generation/parse pair ``run_planner`` uses — no bespoke JSON
        parsing (DRY).  Returns ``([], error_event)`` when the call fails
        or the model does not return a valid, non-empty ordered plan.

        MAJOR 2 fix (GPT-5.5 review round 2): checkpoints BEFORE and AFTER
        the single ``ctx.llm_call`` — matches the ``_run_checkpoint``
        convention used throughout ``run_react``/``run_planner``
        (``react_strategy.py:452-455``, ``planner_strategy.py:46-49``):
        ``await ctx.checkpoint()``, ``None`` = no-op / proceed, a non-``None``
        ``RuntimeEvent`` is the terminal event to surface immediately —
        without it, cancellation arriving AFTER the failed direct attempt
        but BEFORE decomposition would still let ADaPT spend the decompose
        ``ctx.llm_call`` before the next recursive run observes it. A
        checkpoint hit here is returned as the ``decompose_error`` — the
        existing caller (``_run_step``) already yields it and returns,
        skipping decomposition/recursion, no new call-site branch needed.
        """
        if ctx.checkpoint is not None:
            checkpoint_event = await ctx.checkpoint()
            if checkpoint_event is not None:
                return [], checkpoint_event

        decompose_prompt = build_planner_prompt(
            f"{ctx.system_prompt}\n\n"
            f'The step "{title}" FAILED on direct execution. Decompose it '
            "into an ordered list of smaller sub-steps that together "
            "accomplish it.",
            ctx.tools or [],
        )
        try:
            raw = await ctx.llm_call(_messages_to_lm(ctx.messages), decompose_prompt)
        except ThinLlmError as exc:
            return [], RuntimeEvent.error(exc.error)

        if ctx.checkpoint is not None:
            checkpoint_event = await ctx.checkpoint()
            if checkpoint_event is not None:
                return [], checkpoint_event

        plan = parse_plan(raw)
        if plan is None:
            return [], RuntimeEvent.error(
                RuntimeErrorData(
                    kind="bad_model_output",
                    message=f"ADaPT could not decompose step {title!r} into a valid plan",
                    recoverable=False,
                )
            )
        return plan.steps, None
