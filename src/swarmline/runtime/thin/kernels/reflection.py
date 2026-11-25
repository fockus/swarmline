"""ReflectionKernel — critique-and-refine execution kernel grounded in an
external signal, not model self-judgement.

kernel-patterns spec, Task 4 (REQ-003, REQ-009), Scenario 3. ADR "Reflection
заземлён на внешний сигнал" (design.md; arxiv 2310.01798: intrinsic
self-correction WITHOUT an external signal does NOT work — a model
critiquing its own output is not a trustworthy stop condition).
``ReflectionKernel`` REQUIRES an ``ExternalSignal`` at construction — there
is no "pure self-critique" mode and no code path that skips it.

Loop shape, one attempt per iteration, bounded by ``max_iterations``:

    generate (inner ReAct — ``run_react``, reused exactly like
    ``ADaPTKernel`` reuses it)
      -> ``await signal.evaluate(output, ctx)``
      -> IF ``result.passed`` surface the final (terminal, done)
      -> ELSE refine: regenerate with ``result.feedback`` injected into the
         system prompt via ``build_plan_step_prompt`` — the SAME
         prompt-builder ``ADaPTKernel`` reuses for its sub-step context
         threading (DRY, see ``kernels/adapt.py``) — and loop again.

``max_iterations`` bounds the loop independent of whether the signal or the
model ever "cooperates": once the bound is hit WITHOUT the signal ever
passing, ReflectionKernel surfaces a terminal ``error`` (``kind="loop_limit"``)
rather than the last (unvalidated) attempt — see "Exhaustion" below (MAJOR 2,
GPT-5.5 review round 3).

Drop-and-synthesize per attempt (MAJOR 1, GPT-5.5 review round 3; revised
for a MAJOR logic defect found in GPT-5.5 review round 2 of the buffer-and-
flush design): a generation's candidate ANSWER-content events
(``assistant_delta`` / ``thinking_delta`` — the model's own output tokens
for THIS attempt) are DROPPED during generation — neither forwarded nor
buffered. The buffer-and-flush predecessor of this design buffered these
events across the WHOLE ``run_react`` invocation and flushed the buffer
verbatim on ``passed``; but ``run_react`` can, WITHIN ONE invocation, stream
deltas for a malformed attempt whose envelope fails to parse, ``continue``
its internal retry loop, and stream a DIFFERENT attempt's deltas before
finally emitting one ``final`` — so the buffer held BOTH the malformed
attempt's stale text AND the good deltas, and flushing it on ``passed``
leaked the malformed attempt's content to the caller ahead of the validated
answer. Buffering-and-replaying deltas is therefore not safe: it depends on
``run_react``'s internal retry structure never re-streaming across a parse
failure, which does not hold. Instead, once ``signal.evaluate`` returns
``passed=True``, a SINGLE ``RuntimeEvent.assistant_delta`` is SYNTHESIZED
from ``generated.text`` — the exact string the signal validated — and
yielded before the terminal ``final``. This is contamination-proof by
construction: the only answer content the caller ever sees is byte-identical
to the signal-validated text, independent of how many attempts, retries, or
malformed intermediate streams occurred inside ``run_react`` to produce it.
If ``generated.text`` is falsy (empty string), no synthesized delta is
emitted at all — only the terminal ``final``. When the signal returns
``passed=False``, no answer content is emitted for that attempt (it was
already dropped during generation, never buffered, so there is nothing to
discard). Every OTHER non-terminal event a generation yields — ``status`` /
``tool_call_started`` / ``tool_call_finished`` / ``approval_required`` /
``user_input_requested`` / ``native_notice`` / ``background_complete`` — is
true run-progress, not answer content, and is still forwarded immediately
regardless of the eventual verdict.

Error handling (Task 3 discipline, generalised further than ADaPT's):
ANY terminal ``error`` from the inner ``run_react`` — cancelled /
budget_exceeded / runtime_crash / dependency_missing /
capability_unsupported / guardrail_tripwire / mcp_timeout /
bad_model_output / loop_limit / any future/unknown kind — PROPAGATES
immediately; ReflectionKernel never keeps looping past a global/runtime
failure. Unlike ``ADaPTKernel`` (which allow-lists two specific per-step
reasoning-failure kinds as "safe to retry via decompose"), Reflection has NO
allow-list at all: only a generation that SUCCEEDS and then FAILS the
external signal's ``passed`` check is ever refined. A run_react error is
never itself a signal to refine — refining on top of it would paper over a
runtime/provider failure exactly the way ADaPT's MAJOR-1 allow-list fix
forbids for decompose (see ``adapt.py`` module docstring).

Checkpoint discipline (mirrors ``adapt.py::_decompose``): ``run_react``
already polls ``ctx.checkpoint`` internally throughout generation, so this
module does NOT add a redundant checkpoint before starting one. It DOES add
two extra checkpoint calls per iteration — immediately before and after
``signal.evaluate`` — because that external call is a step run_react's own
internal checkpoints do not cover, exactly the reasoning ``_decompose`` uses
around its one extra ``ctx.llm_call``. A checkpoint hit at either point is
returned as the run's terminal event immediately (no refine, no further
generation).

Exhaustion (MAJOR 2, GPT-5.5 review round 3): once ``iteration ==
max_iterations`` and the signal STILL has not passed, ReflectionKernel does
NOT surface the last attempt as a normal `final` — that would be
indistinguishable from a signal-APPROVED answer at the observable boundary,
losing REQ-009 grounding exactly where it matters most (the caller cannot
tell "the signal approved this" from "we simply ran out of budget"). It
instead yields a single terminal ``RuntimeEvent.error(kind="loop_limit",
...)`` — mirroring how ``ADaPTKernel`` surfaces failure at its own
``max_depth`` bound (``adapt.py:194-206``) — whose ``details`` carry the
last attempt's output text and the last ``SignalResult.feedback``, so the
caller can still inspect what was tried and why it kept failing. The failed
last attempt's answer-content was already dropped during generation (per the
drop-and-synthesize rule above), so nothing is ever synthesized or emitted
for it.

Exactly one terminal per run (by construction): every loop iteration either
(a) forwards a run_react error and returns, (b) forwards a checkpoint's
cancellation event and returns, (c) synthesizes a single answer-content
delta from the validated ``generated.text`` (when non-empty) then yields the
untouched `final` event and returns once the signal passes —
usage/metrics/new_messages are never zeroed or rewritten (H4-Task1 bug
class), or (d) exhausts ``max_iterations`` without a pass and yields the
single ``loop_limit`` terminal error described above.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from swarmline.runtime.thin.prompts import build_plan_step_prompt
from swarmline.runtime.thin.react_strategy import run_react
from swarmline.runtime.types import RuntimeErrorData, RuntimeEvent

if TYPE_CHECKING:
    from swarmline.protocols.external_signal import ExternalSignal
    from swarmline.types import KernelContext

# MAJOR 1 (GPT-5.5 review round 3), revised for the MAJOR logic defect found
# in GPT-5.5 review round 2: candidate ANSWER-content event types — the
# model's own output tokens for the attempt currently being generated (its
# streamed final-answer text, or its reasoning about it). These are DROPPED
# during generation (neither forwarded nor buffered) because ``run_react``
# can re-stream a DIFFERENT attempt's deltas within one invocation after a
# parse-failure retry, and buffering-and-replaying them would leak the
# discarded attempt's content. Once ``signal.evaluate`` passes, the validated
# answer is instead RE-SYNTHESIZED as a single ``assistant_delta`` from
# ``generated.text`` — see the module docstring's "Drop-and-synthesize"
# section. Every other non-terminal RuntimeEvent type (status,
# tool_call_started/finished, approval_required, user_input_requested,
# native_notice, background_complete — see RUNTIME_EVENT_TYPES in
# domain_types.py) is run-progress, not answer content, and is forwarded
# immediately regardless of the eventual verdict.
_ANSWER_CONTENT_EVENT_TYPES: frozenset[str] = frozenset(
    {"assistant_delta", "thinking_delta"}
)


class ReflectionKernel:
    """Generate -> external-signal critique -> refine, bounded by max_iterations.

    ``signal`` is REQUIRED (REQ-009): no default, no None-tolerant fallback.
    ``max_iterations`` is a constructor argument, not a ``KernelContext``
    field — same pattern ``ADaPTKernel.max_depth`` uses: it configures the
    KERNEL instance, while all per-run inputs still flow through ``ctx``.
    """

    def __init__(self, signal: ExternalSignal, max_iterations: int = 3) -> None:
        if signal is None:
            raise ValueError("ReflectionKernel requires an ExternalSignal (not None)")
        if max_iterations < 1:
            # MAJOR 3 (GPT-5.5 review round 3): fail fast at construction
            # rather than silently skipping the loop body and crashing the
            # internal ``assert last_final is not None`` later — an
            # ExecutionKernel must never crash the contract.
            raise ValueError(
                "ReflectionKernel requires max_iterations >= 1 "
                f"(got {max_iterations!r})"
            )
        self._signal = signal
        self._max_iterations = max_iterations

    def run(self, ctx: KernelContext) -> AsyncIterator[RuntimeEvent]:
        """Run generate -> evaluate -> refine, bounded by max_iterations."""
        if ctx.executor is None:
            raise ValueError("ReflectionKernel requires ctx.executor (not None)")
        return self._run(ctx)

    async def _run(self, ctx: KernelContext) -> AsyncIterator[RuntimeEvent]:
        assert ctx.executor is not None  # guaranteed by run() above
        system_prompt = ctx.system_prompt

        for iteration in range(1, self._max_iterations + 1):
            generated: RuntimeEvent | None = None
            # MAJOR 1 (GPT-5.5 review round 3), revised per the MAJOR logic
            # defect found in GPT-5.5 review round 2: DROP this attempt's
            # candidate ANSWER-content events (assistant_delta /
            # thinking_delta) instead of forwarding OR buffering them.
            # Forwarding them before signal.evaluate runs would stream a
            # candidate the signal may yet REJECT; buffering-and-replaying
            # them was found unsafe because run_react can re-stream a
            # DIFFERENT (parse-failed) attempt's deltas within one
            # invocation — a buffer would capture both and leak the
            # discarded attempt's text on flush. The validated answer is
            # re-synthesized from ``generated.text`` below once the signal
            # passes (see module docstring, "Drop-and-synthesize"). Every
            # OTHER non-terminal event (status / tool_call_started /
            # tool_call_finished / approval_required / user_input_requested
            # / native_notice / background_complete) is true run-progress,
            # not answer content, and is still forwarded immediately.
            async for event in run_react(
                ctx.llm_call,
                ctx.executor,
                ctx.messages,
                system_prompt,
                ctx.tools or [],
                ctx.config,
                ctx.start_time,
                checkpoint=ctx.checkpoint,
                on_retry=ctx.on_retry,
                native_adapter=ctx.native_adapter,
                session_dispatcher=ctx.session_dispatcher,
            ):
                if event.is_error:
                    # Global/runtime failure (no allow-list here, unlike
                    # ADaPT): propagate as-is and stop. Refining on top of
                    # it would mask the failure, not fix a critique.
                    yield event
                    return
                if event.is_final:
                    generated = event
                elif event.type in _ANSWER_CONTENT_EVENT_TYPES:
                    # Dropped: never forwarded, never buffered — see the
                    # module docstring's "Drop-and-synthesize" section.
                    continue
                else:
                    yield event

            if generated is None:
                # Dead-by-default corner: react_strategy.py's opt-in
                # self-evolution "stuck escalation" path can end a stream
                # with only a status event and no terminal at all (see
                # adapt.py's module docstring for the same corner). No
                # output means no signal to ground a refine on.
                yield RuntimeEvent.error(
                    RuntimeErrorData(
                        kind="runtime_crash",
                        message=(
                            "ReflectionKernel: generation ended without a "
                            "terminal event"
                        ),
                        recoverable=False,
                    )
                )
                return

            output_text = generated.text

            # Checkpoint around signal.evaluate (mirrors adapt.py's
            # _decompose discipline around its one extra ctx.llm_call — the
            # ONE step run_react's own internal checkpoints do not cover).
            if ctx.checkpoint is not None:
                checkpoint_event = await ctx.checkpoint()
                if checkpoint_event is not None:
                    yield checkpoint_event
                    return

            result = await self._signal.evaluate(output_text, ctx)

            if ctx.checkpoint is not None:
                checkpoint_event = await ctx.checkpoint()
                if checkpoint_event is not None:
                    yield checkpoint_event
                    return

            if result.passed:
                # MAJOR 1, revised: NOW that the signal has validated this
                # attempt, SYNTHESIZE a single assistant_delta from
                # ``output_text`` — exactly what signal.evaluate validated —
                # instead of replaying the (dropped) raw per-token deltas.
                # This is contamination-proof by construction: it cannot
                # carry any malformed/rejected attempt's text, regardless of
                # how run_react internally retried to produce ``generated``.
                if output_text:
                    yield RuntimeEvent.assistant_delta(output_text)
                yield generated
                return

            if iteration == self._max_iterations:
                # MAJOR 2 (GPT-5.5 review round 3): the bound is reached
                # WITHOUT the signal ever passing. Surfacing the last
                # attempt as a normal `final` here would be indistinguishable
                # from a signal-APPROVED answer at the observable boundary —
                # REQ-009 grounding lost. Mirror ADaPTKernel's max_depth
                # error (adapt.py:194-206): a single terminal
                # RuntimeEvent.error(kind="loop_limit", ...) instead. The
                # failed last attempt's answer-content was already dropped
                # during generation (never buffered), per MAJOR 1 — an
                # attempt the signal rejected never reaches the caller and
                # nothing is synthesized for it.
                yield RuntimeEvent.error(
                    RuntimeErrorData(
                        kind="loop_limit",
                        message=(
                            "ReflectionKernel: external signal never passed "
                            f"within max_iterations ({self._max_iterations})"
                        ),
                        details={
                            "last_output": output_text,
                            "last_feedback": result.feedback,
                        },
                        recoverable=False,
                    )
                )
                return

            yield RuntimeEvent.status(
                f"Reflection: iteration {iteration}/{self._max_iterations} "
                "failed the external signal — refining"
            )

            # REQ-009: the NEXT generation's context carries the EXTERNAL
            # signal's feedback, never model self-critique. Reuses
            # build_plan_step_prompt — the SAME prompt-builder ADaPTKernel
            # uses to thread sub-step context (DRY, see kernels/adapt.py) —
            # always derived from the ORIGINAL ctx.system_prompt (not the
            # previous iteration's already-wrapped prompt) so refine prompts
            # do not compound/grow across iterations.
            system_prompt = build_plan_step_prompt(
                ctx.system_prompt,
                "Refine your previous answer using the external signal's feedback",
                f"Previous attempt:\n{output_text}\n\n"
                f"External signal feedback:\n{result.feedback}",
                ctx.tools or [],
            )
