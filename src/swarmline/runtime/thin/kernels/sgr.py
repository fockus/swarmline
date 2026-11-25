"""SGRKernel — typed-NextStep-driven execution kernel with ReAct fallback.

kernel-patterns spec, Task 5 (REQ-004, REQ-011), Scenario 2. ADR "SGR
переиспользует parse_nextstep как драйвер" (design.md): swarmline already
parses a typed ``NextStep`` (``swarmline.orchestration.nextstep``), but
historically only as METADATA threaded alongside a taskloom-style agent.
``SGRKernel`` makes ``NextStep`` the control-flow DRIVER itself: each loop
iteration asks the model for one typed ``NextStep`` and dispatches on its
``action`` field, not on free-form text.

Loop shape, bounded by ``max_steps`` (constructor argument — same pattern
as ``ADaPTKernel.max_depth`` / ``ReflectionKernel.max_iterations``: it
configures the KERNEL instance, all per-run inputs still flow through
``ctx``)::

    for step_num in 1..max_steps:
        generate one NextStep (``ctx.llm_call`` against ``ctx.system_prompt``
        + ``nextstep_system_instruction()``, checkpointed before/after)
        parse_nextstep(raw)
          -> None (parse/validation failure): ReAct fallback (REQ-011),
             turn COMPLETES via run_react's own terminal -- never a failed
             turn just because the model didn't emit valid JSON.
          -> NextStep: dispatch on step.action.strip().upper():
               TOOL_CALL          -> delegate this turn to run_react
               FINAL              -> delegate a finalizing turn to
                                     run_react (NextStep carries no answer
                                     text of its own)
               ASK_CLARIFICATION  -> terminal user_input_requested
               REPLAN             -> status + `continue` (next NextStep)
               FAIL               -> terminal error
               <anything else>    -> ReAct fallback (REQ-011 spirit: an
                                     unrecognised action is exactly as
                                     untrustworthy as unparseable JSON)
    max_steps exhausted (reachable ONLY when every iteration was REPLAN --
    every other branch above `return`s) -> terminal error
    (kind="loop_limit"), mirroring ADaPTKernel's/ReflectionKernel's own
    exhaustion errors.

Why TOOL_CALL/FINAL delegate to run_react instead of executing directly:
``NextStep`` (``swarmline/orchestration/nextstep.py``) has NO structured
tool-name/args field and NO answer-text field -- it is a reasoning
SNAPSHOT (current_state/plan/options/reasoning/action/confidence), not a
tool-call envelope. ``run_react`` already owns the tool-call envelope,
tool execution, and structured-output finalization (reused exactly as
``ADaPTKernel``/``ReflectionKernel`` reuse it) -- SGR's job is choosing
WHEN to invoke it and WHY (the NextStep action), not re-implementing it.
Both branches forward every event run_react yields untouched and return
right after: run_react guarantees exactly one terminal (final or error)
per invocation in the common case (see adapt.py's module docstring), so
no is_final/is_error follow-up DECISION is needed here -- unlike
ADaPTKernel, SGR never branches on that terminal's content. ``_delegate``
DOES track whether a terminal was actually observed, purely as a safety
net: react_strategy.py documents an opt-in, dead-by-default corner
(self-evolution "stuck escalation") where run_react's own stream can end
after a status event with zero terminals. If that happens, ``_delegate``
synthesizes a terminal ``error`` (kind="runtime_crash") before returning,
mirroring reflection.py's ``generated is None`` guard exactly -- SGRKernel
never ends a run silently with zero terminals.

FAIL error-kind mapping: RUNTIME_ERROR_KINDS (domain_types.py) has no
"agent declared failure" kind. ``runtime_crash`` is chosen as the
least-wrong existing kind -- it is RuntimeErrorData's own fallback default
for any kind that does not fit (``__post_init__``), and ReflectionKernel
already reaches for it in an analogous "no existing kind fits" corner (a
generation that ends without any terminal event at all). A more precise
kind (e.g. "agent_declared_failure") is NOT added in this task (YAGNI,
out of scope) -- noted here for the Task 6 registration backlog.

REQ-011 fallback (parse failure OR unrecognised action): the fallback
ALWAYS reuses the ORIGINAL ``ctx.system_prompt`` -- never the
SGR-instrumented ("+ nextstep_system_instruction()") prompt, which is
built into a LOCAL variable each iteration and never written back onto
``ctx`` (``ctx`` is a frozen dataclass; SGR never calls
``dataclasses.replace`` on it).

Exactly one terminal per run (by construction): every iteration either
(a) yields a checkpoint's cancellation/other terminal event and returns,
(b) forwards run_react's fallback stream (which itself yields exactly one
terminal -- final or error -- REQ-011) and returns, (c) forwards a
delegated TOOL_CALL/FINAL run_react stream (same one-terminal guarantee)
and returns, (d) yields a single terminal ``user_input_requested``
(ASK_CLARIFICATION) and returns, (e) yields a single terminal ``error``
(FAIL) and returns, or (f) -- only after every iteration chose REPLAN --
yields the single ``loop_limit`` exhaustion error. REPLAN is the ONLY
branch that does not `return`, so max_steps exhaustion is only reachable
when every single iteration chose REPLAN.

Surfaced run_react finals are yielded UNTOUCHED (no ``dataclasses.replace``)
so usage/metrics/new_messages are exactly what run_react /
``finalize_with_validation`` computed for that generation -- never zeroed
or hand-reconstructed (H4-Task1 bug class; mirrors ADaPTKernel /
ReflectionKernel).

ANY terminal ``error`` a delegated ``run_react`` call yields (TOOL_CALL or
FINAL branch, or the REQ-011 fallback) PROPAGATES immediately -- no
allow-list, unlike ADaPTKernel's decompose retry: SGR never keeps
generating NextSteps past a runtime/provider failure it cannot see inside.

Checkpoint discipline (mirrors ``adapt.py::_decompose`` /
``reflection.py``'s pre/post-``signal.evaluate`` checks): ``run_react``
already polls ``ctx.checkpoint`` internally throughout ITS OWN generation,
so this module does not add a redundant checkpoint around a delegated
``run_react`` call. It DOES add two checkpoint calls per iteration --
immediately before and after the NextStep-generation ``ctx.llm_call`` --
because that call is a step none of run_react's internal checkpoints
cover. A checkpoint hit at either point is returned as the run's terminal
event immediately (no generation, no action dispatch).

``confidence`` (``step.confidence``, 0.0-1.0) is available on every parsed
NextStep and surfaced in the branch-choice ``status`` events so callers
can observe it, but no mandatory confidence GATE is added here (YAGNI --
no test in this task requires one).
# ponytail: a confidence gate (e.g. "treat as REPLAN if confidence is
# below a threshold, regardless of action") would hook in right after
# `step = parse_nextstep(...)` below, before the action dispatch -- left
# unbuilt until a concrete need demands it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from swarmline.orchestration.nextstep import (
    NextStep,
    nextstep_system_instruction,
    parse_nextstep,
)
from swarmline.runtime.thin.errors import ThinLlmError
from swarmline.runtime.thin.helpers import _messages_to_lm
from swarmline.runtime.thin.react_strategy import run_react
from swarmline.runtime.types import RuntimeErrorData, RuntimeEvent

if TYPE_CHECKING:
    from swarmline.types import KernelContext

# FAIL error-kind mapping (see module docstring, "FAIL error-kind mapping").
_FAIL_ERROR_KIND = "runtime_crash"


class SGRKernel:
    """Drive control-flow by a typed NextStep's ``action``, bounded by
    ``max_steps``; ReAct fallback on parse failure or an unrecognised
    action (REQ-011). See the module docstring for the full loop-shape,
    action-dispatch table, and discipline rationale.
    """

    def __init__(self, max_steps: int = 8) -> None:
        if max_steps < 1:
            raise ValueError(f"SGRKernel requires max_steps >= 1 (got {max_steps!r})")
        self._max_steps = max_steps

    def run(self, ctx: KernelContext) -> AsyncIterator[RuntimeEvent]:
        """Drive the loop by typed NextStep, bounded by max_steps."""
        if ctx.executor is None:
            raise ValueError("SGRKernel requires ctx.executor (not None)")
        return self._run(ctx)

    async def _run(self, ctx: KernelContext) -> AsyncIterator[RuntimeEvent]:
        assert ctx.executor is not None  # guaranteed by run() above
        original_system_prompt = ctx.system_prompt
        last_action = ""
        last_reasoning = ""

        for step_num in range(1, self._max_steps + 1):
            if ctx.checkpoint is not None:
                checkpoint_event = await ctx.checkpoint()
                if checkpoint_event is not None:
                    yield checkpoint_event
                    return

            # LOCAL variable only -- never written back onto ctx (ctx is a
            # frozen dataclass; SGR never calls dataclasses.replace on it).
            sgr_prompt = f"{original_system_prompt}\n\n{nextstep_system_instruction()}"

            try:
                raw = await ctx.llm_call(_messages_to_lm(ctx.messages), sgr_prompt)
            except ThinLlmError as exc:
                yield RuntimeEvent.error(exc.error)
                return

            if ctx.checkpoint is not None:
                checkpoint_event = await ctx.checkpoint()
                if checkpoint_event is not None:
                    yield checkpoint_event
                    return

            step = parse_nextstep(raw)
            if step is None:
                # REQ-011: unparseable NextStep -- fall back to ReAct on the
                # ORIGINAL prompt. The turn COMPLETES via run_react's own
                # terminal; never a failed turn.
                async for event in self._delegate(ctx, original_system_prompt):
                    yield event
                return

            action = step.action.strip().upper()
            last_action, last_reasoning = action, step.reasoning

            if action == "TOOL_CALL":
                yield RuntimeEvent.status(
                    f"SGR: NextStep action=TOOL_CALL (confidence="
                    f"{step.confidence:.2f}) -- delegating to ReAct"
                )
                async for event in self._delegate(ctx, original_system_prompt):
                    yield event
                return

            if action == "FINAL":
                yield RuntimeEvent.status(
                    f"SGR: NextStep action=FINAL (confidence="
                    f"{step.confidence:.2f}) -- finalizing via ReAct"
                )
                async for event in self._delegate(ctx, original_system_prompt):
                    yield event
                return

            if action == "ASK_CLARIFICATION":
                yield RuntimeEvent.user_input_requested(
                    prompt=_clarification_prompt(step)
                )
                return

            if action == "REPLAN":
                yield RuntimeEvent.status(
                    f"SGR: NextStep action=REPLAN (step {step_num}/"
                    f"{self._max_steps}) -- re-planning"
                )
                continue

            if action == "FAIL":
                yield RuntimeEvent.error(
                    RuntimeErrorData(
                        kind=_FAIL_ERROR_KIND,
                        message=f"SGR: agent declared FAIL -- {step.reasoning}",
                        details={
                            "reasoning": step.reasoning,
                            "current_state": step.current_state,
                        },
                        recoverable=False,
                    )
                )
                return

            # Unrecognised action: exactly as untrustworthy as unparseable
            # JSON (REQ-011 spirit) -- fall back to ReAct rather than fail.
            async for event in self._delegate(ctx, original_system_prompt):
                yield event
            return

        # Reached only when EVERY iteration chose REPLAN (every other
        # branch above `return`s) -- mirrors ADaPTKernel's max_depth /
        # ReflectionKernel's max_iterations exhaustion errors.
        yield RuntimeEvent.error(
            RuntimeErrorData(
                kind="loop_limit",
                message=(
                    f"SGRKernel: max_steps ({self._max_steps}) exhausted "
                    "without a terminal NextStep action"
                ),
                details={"last_action": last_action, "last_reasoning": last_reasoning},
                recoverable=False,
            )
        )

    async def _delegate(
        self, ctx: KernelContext, system_prompt: str
    ) -> AsyncIterator[RuntimeEvent]:
        """Delegate this turn's execution to run_react, forwarding every
        event untouched (final/error surfaced as-is -- usage/metrics/
        new_messages preserved, H4-Task1 bug class).

        Tracks whether a run_react terminal (final or error) was actually
        observed. react_strategy.py's opt-in, dead-by-default self-evolution
        "stuck escalation" corner can end run_react's stream after a status
        event with ZERO terminals -- if that happens, synthesize one before
        returning so SGRKernel never ends a run silently with zero
        terminals, mirroring reflection.py's ``generated is None`` guard
        exactly (same kind, same rationale)."""
        assert ctx.executor is not None
        terminal_seen = False
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
            if event.is_final or event.is_error:
                terminal_seen = True
            yield event

        if not terminal_seen:
            yield RuntimeEvent.error(
                RuntimeErrorData(
                    kind="runtime_crash",
                    message=(
                        "SGRKernel: delegated run_react ended without a terminal event"
                    ),
                    recoverable=False,
                )
            )


def _clarification_prompt(step: NextStep) -> str:
    """Build the ASK_CLARIFICATION prompt text from reasoning + current_state."""
    parts = [p for p in (step.reasoning, step.current_state) if p]
    return " -- ".join(parts) if parts else "SGR requested clarification"
