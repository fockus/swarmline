"""TDD tests for kernel-patterns spec, Task 3 — ADaPTKernel.

Covers REQ-002, REQ-007, REQ-008, Scenario 1 (decompose-on-failure,
depth-bounded ADaPT: arxiv 2311.05772).  Written BEFORE the implementation
(TDD RED -> GREEN); see ``ADaPTKernel`` in
``swarmline.runtime.thin.kernels.adapt`` for the design rationale.

Failure signal under test: ``run_react`` (and
``finalization.finalize_with_validation``) always end their stream with
EXACTLY ONE terminal ``RuntimeEvent`` — ``type == "final"`` on success or
``type == "error"`` on failure.  These tests drive that signal via a fake
``llm_call`` (real ``run_react``/``ToolExecutor``, no mocking of the
strategy layer itself) so the ADaPT control-flow is exercised end-to-end.
"""

from __future__ import annotations

import json
from typing import Any


from swarmline.domain_types import RuntimeEvent
from swarmline.runtime.thin.executor import ToolExecutor
from swarmline.runtime.types import RuntimeConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _noop_checkpoint() -> RuntimeEvent | None:
    return None


def _make_context(**overrides: Any) -> Any:
    """Build a minimal valid KernelContext for testing (real ToolExecutor)."""
    from swarmline.types import KernelContext

    defaults: dict[str, Any] = {
        "llm_call": None,
        "messages": [],
        "system_prompt": "You are a helper.",
        "config": RuntimeConfig(runtime_name="thin"),
        "start_time": 0.0,
        "checkpoint": _noop_checkpoint,
        "executor": ToolExecutor(),
    }
    defaults.update(overrides)
    return KernelContext(**defaults)


# ===========================================================================
# Simple path — direct success, no decomposition (REQ-002)
# ===========================================================================


class TestADaPTSimpleStepSuccess:
    async def test_adapt_simple_step_runs_without_decomposition(self) -> None:
        """A step that succeeds directly emits success WITHOUT any decompose
        LLM call — the simple path never decomposes (REQ-002)."""
        from swarmline.runtime.thin.kernels.adapt import ADaPTKernel

        call_count = 0

        async def llm_call(messages: Any, prompt: Any, **kw: Any) -> str:
            nonlocal call_count
            call_count += 1
            return json.dumps({"type": "final", "final_message": "done"})

        ctx = _make_context(llm_call=llm_call)
        kernel = ADaPTKernel()
        events = [ev async for ev in kernel.run(ctx)]

        assert call_count == 1, "Direct success must not trigger a decompose call"

        finals = [ev for ev in events if ev.is_final]
        assert len(finals) == 1, f"Expected exactly one terminal final; got: {events}"
        assert finals[0].data.get("text") == "done"

        errors = [ev for ev in events if ev.is_error]
        assert errors == [], f"No error expected on the simple path; got: {errors}"

        status_texts = [ev.text for ev in events if ev.type == "status"]
        assert not any("decompos" in t.lower() for t in status_texts), (
            f"No decomposition expected on the simple path; got: {status_texts}"
        )


# ===========================================================================
# Decompose-on-failure — Scenario 1 / REQ-007
# ===========================================================================


class TestADaPTDecomposesOnFailure:
    async def test_adapt_decomposes_failed_step_and_retries(self) -> None:
        """Scenario 1 / REQ-007: a step that FAILS on direct execution is
        decomposed into ordered sub-steps, which are then executed in order.

        The fake llm_call branches on the (real, composed) prompt content so
        each physical sub-step call is answered with ITS OWN response —
        letting the resulting event order prove genuine step ordering,
        not a tautology of a fixed response list.
        """
        from swarmline.runtime.thin.kernels.adapt import ADaPTKernel

        decompose_plan = json.dumps(
            {
                "type": "plan",
                "goal": "recover from failure",
                "steps": [
                    {"id": "s1", "title": "Sub Alpha", "mode": "react"},
                    {"id": "s2", "title": "Sub Beta", "mode": "react"},
                ],
                "final_format": "",
            }
        )
        call_count = 0

        async def llm_call(messages: Any, prompt: Any, **kw: Any) -> str:
            nonlocal call_count
            call_count += 1
            if '"type": "plan"' in prompt:
                return decompose_plan
            if "Sub Alpha" in prompt:
                return json.dumps({"type": "final", "final_message": "alpha done"})
            if "Sub Beta" in prompt:
                return json.dumps({"type": "final", "final_message": "beta done"})
            # top-level direct attempt: unparseable, brace-wrapped -> no text
            # fallback either -> forces run_react's bad_model_output error.
            return "{not valid json}"

        config = RuntimeConfig(runtime_name="thin", max_model_retries=0)
        ctx = _make_context(llm_call=llm_call, config=config)
        kernel = ADaPTKernel()
        events = [ev async for ev in kernel.run(ctx)]

        assert call_count == 4, (
            f"Expected 4 llm_call invocations (fail, decompose, Sub Alpha, "
            f"Sub Beta); got {call_count}"
        )

        status_texts = [ev.text for ev in events if ev.type == "status"]
        assert any("decompos" in t.lower() for t in status_texts), (
            f"Expected a decomposition status; got: {status_texts}"
        )

        # Sub-steps ran, IN ORDER: Alpha's own text appears before Beta's.
        deltas = [ev.text for ev in events if ev.type == "assistant_delta"]
        assert "alpha done" in deltas and "beta done" in deltas, (
            f"Expected both sub-step results streamed; got: {deltas}"
        )
        assert deltas.index("alpha done") < deltas.index("beta done"), (
            f"Expected Sub Alpha before Sub Beta; got: {deltas}"
        )

        finals = [ev for ev in events if ev.is_final]
        assert len(finals) == 1, f"Expected exactly one terminal final; got: {events}"
        assert finals[0].data.get("text") == "beta done"

        errors = [ev for ev in events if ev.is_error]
        assert errors == [], (
            f"Expected no surfaced error (recovered via decompose); got: {errors}"
        )


# ===========================================================================
# Depth bound — REQ-008
# ===========================================================================


class TestADaPTMaxDepth:
    async def test_adapt_stops_at_max_depth_and_surfaces_failure(self) -> None:
        """REQ-008: once max_depth is reached, ADaPT stops decomposing and
        surfaces exactly one terminal failure — with a bounded (non-runaway)
        recursion / call count.

        Direct attempts fail instantly via ``max_iterations=0`` (deterministic,
        zero-llm_call failure signal — see react_strategy's loop_limit guard),
        so only the decompose calls consume llm_call: at most ``max_depth``.
        """
        from swarmline.runtime.thin.kernels.adapt import ADaPTKernel

        call_count = 0

        async def llm_call(messages: Any, prompt: Any, **kw: Any) -> str:
            nonlocal call_count
            call_count += 1
            # Always hand back one more sub-step that will fail again too,
            # forcing recursion all the way to the depth bound.
            return json.dumps(
                {
                    "type": "plan",
                    "goal": "still failing",
                    "steps": [{"id": "s1", "title": "still fails", "mode": "react"}],
                    "final_format": "",
                }
            )

        config = RuntimeConfig(runtime_name="thin", max_iterations=0)
        ctx = _make_context(llm_call=llm_call, config=config)
        kernel = ADaPTKernel(max_depth=2)
        events = [ev async for ev in kernel.run(ctx)]

        assert call_count == 2, (
            f"Expected exactly max_depth (2) decompose calls, no runaway "
            f"recursion; got {call_count}"
        )

        errors = [ev for ev in events if ev.is_error]
        assert len(errors) == 1, f"Expected exactly one terminal failure; got: {events}"
        message = errors[0].data.get("message", "")
        assert "max_depth" in message and "2" in message, (
            f"Expected the failure to name max_depth (2); got: {message!r}"
        )

        finals = [ev for ev in events if ev.is_final]
        assert finals == [], "No success should be reported when the bound is hit"


# ===========================================================================
# MAJOR 1 (VERIFY-gate) — global/unrecoverable errors must PROPAGATE, not
# trigger a decompose retry (cancellation must not keep working after being
# cancelled; budget-exceeded must not spend MORE tokens).
# ===========================================================================


class TestADaPTPropagatesGlobalErrors:
    async def test_adapt_propagates_cancelled_without_decomposing(self) -> None:
        """A step whose inner run_react is cancelled (checkpoint fires
        kind='cancelled') must propagate that exact error — NOT trigger a
        decompose llm_call (which would keep "working" after cancellation)."""
        from swarmline.runtime.thin.kernels.adapt import ADaPTKernel
        from swarmline.runtime.thin.runtime_support import cancelled_event

        call_count = 0

        async def llm_call(messages: Any, prompt: Any, **kw: Any) -> str:
            nonlocal call_count
            call_count += 1
            return json.dumps({"type": "final", "final_message": "should not run"})

        class _CancelledToken:
            is_cancelled = True

        async def cancelling_checkpoint() -> Any:
            return cancelled_event(_CancelledToken())

        ctx = _make_context(llm_call=llm_call, checkpoint=cancelling_checkpoint)
        kernel = ADaPTKernel()
        events = [ev async for ev in kernel.run(ctx)]

        assert call_count == 0, (
            "Cancellation must short-circuit before ANY llm_call (direct "
            f"attempt or decompose); got {call_count} calls"
        )

        errors = [ev for ev in events if ev.is_error]
        assert len(errors) == 1, f"Expected exactly one terminal error; got: {events}"
        assert errors[0].data.get("kind") == "cancelled", (
            f"Expected the propagated error to keep kind='cancelled'; got: {errors[0].data}"
        )

        status_texts = [ev.text for ev in events if ev.type == "status"]
        assert not any("decompos" in t.lower() for t in status_texts), (
            f"No decomposition expected for a cancelled run; got: {status_texts}"
        )

        finals = [ev for ev in events if ev.is_final]
        assert finals == [], "No success should be reported when cancelled"

    async def test_adapt_propagates_budget_exceeded_without_decomposing(self) -> None:
        """A step whose inner run_react hits the tool-call budget (kind=
        'budget_exceeded') must propagate that exact error — NOT decompose
        and spend MORE tokens on top of an already-exhausted budget."""
        from swarmline.runtime.thin.kernels.adapt import ADaPTKernel

        call_count = 0

        async def llm_call(messages: Any, prompt: Any, **kw: Any) -> str:
            nonlocal call_count
            call_count += 1
            return json.dumps(
                {
                    "type": "tool_call",
                    "tool": {"name": "noop", "args": {}, "correlation_id": "c1"},
                    "assistant_message": "",
                }
            )

        config = RuntimeConfig(runtime_name="thin", max_tool_calls=0)
        ctx = _make_context(llm_call=llm_call, config=config)
        kernel = ADaPTKernel()
        events = [ev async for ev in kernel.run(ctx)]

        assert call_count == 1, (
            "budget_exceeded fires on the FIRST tool_call envelope; no "
            f"decompose llm_call expected; got {call_count} calls"
        )

        errors = [ev for ev in events if ev.is_error]
        assert len(errors) == 1, f"Expected exactly one terminal error; got: {events}"
        assert errors[0].data.get("kind") == "budget_exceeded", (
            f"Expected the propagated error to keep kind='budget_exceeded'; "
            f"got: {errors[0].data}"
        )

        status_texts = [ev.text for ev in events if ev.type == "status"]
        assert not any("decompos" in t.lower() for t in status_texts), (
            f"No decomposition expected when the tool-call budget is exhausted; "
            f"got: {status_texts}"
        )

        finals = [ev for ev in events if ev.is_final]
        assert finals == [], (
            "No success should be reported when the budget is exhausted"
        )

    async def test_adapt_propagates_runtime_crash_without_decomposing(self) -> None:
        """A step whose inner direct attempt terminates with a
        ``runtime_crash`` (provider/API failure, runtime itself is broken —
        NOT a per-step reasoning failure) must PROPAGATE that exact error and
        make NO decompose ``llm_call`` — decomposing on top of a broken
        runtime would spend a decompose call trying to "fix" a healthy step
        whose provider just crashed, silently masking the crash as a step
        failure (GPT-5.5 review round 2, MAJOR 1)."""
        from swarmline.runtime.thin.errors import ThinLlmError
        from swarmline.runtime.thin.kernels.adapt import ADaPTKernel
        from swarmline.runtime.types import RuntimeErrorData

        call_count = 0

        async def llm_call(messages: Any, prompt: Any, **kw: Any) -> str:
            nonlocal call_count
            call_count += 1
            raise ThinLlmError(
                RuntimeErrorData(kind="runtime_crash", message="provider crashed")
            )

        ctx = _make_context(llm_call=llm_call)
        kernel = ADaPTKernel()
        events = [ev async for ev in kernel.run(ctx)]

        assert call_count == 1, (
            "runtime_crash must propagate right after the direct attempt — "
            f"no decompose llm_call expected; got {call_count} calls"
        )

        errors = [ev for ev in events if ev.is_error]
        assert len(errors) == 1, f"Expected exactly one terminal error; got: {events}"
        assert errors[0].data.get("kind") == "runtime_crash", (
            f"Expected the propagated error to keep kind='runtime_crash'; "
            f"got: {errors[0].data}"
        )

        status_texts = [ev.text for ev in events if ev.type == "status"]
        assert not any("decompos" in t.lower() for t in status_texts), (
            f"No decomposition expected for a runtime crash; got: {status_texts}"
        )

        finals = [ev for ev in events if ev.is_final]
        assert finals == [], "No success should be reported when the runtime crashed"


class TestADaPTDecomposableKindsStillDecompose:
    """Guard against over-propagating the MAJOR 1 allow-list fix: kinds that
    signal a per-step reasoning failure with a HEALTHY runtime
    (``loop_limit`` — iteration budget exhausted without converging;
    ``bad_model_output`` — the model's response didn't parse) must still
    trigger a decompose retry, exactly like before the fix."""

    async def test_adapt_bad_model_output_still_decomposes_and_recovers(self) -> None:
        """bad_model_output (unparseable model response) is decomposable —
        the direct attempt fails, ADaPT decomposes, and the sub-steps run and
        recover to a single terminal success."""
        from swarmline.runtime.thin.kernels.adapt import ADaPTKernel

        decompose_plan = json.dumps(
            {
                "type": "plan",
                "goal": "recover from failure",
                "steps": [{"id": "s1", "title": "Sub Alpha", "mode": "react"}],
                "final_format": "",
            }
        )
        call_count = 0

        async def llm_call(messages: Any, prompt: Any, **kw: Any) -> str:
            nonlocal call_count
            call_count += 1
            if '"type": "plan"' in prompt:
                return decompose_plan
            if "Sub Alpha" in prompt:
                return json.dumps({"type": "final", "final_message": "alpha done"})
            # top-level direct attempt: unparseable -> bad_model_output.
            return "{not valid json}"

        config = RuntimeConfig(runtime_name="thin", max_model_retries=0)
        ctx = _make_context(llm_call=llm_call, config=config)
        kernel = ADaPTKernel()
        events = [ev async for ev in kernel.run(ctx)]

        assert call_count == 3, (
            f"Expected 3 llm_call invocations (bad_model_output direct "
            f"attempt, decompose, Sub Alpha); got {call_count}"
        )

        status_texts = [ev.text for ev in events if ev.type == "status"]
        assert any("decompos" in t.lower() for t in status_texts), (
            f"Expected bad_model_output to still trigger decomposition; "
            f"got: {status_texts}"
        )

        finals = [ev for ev in events if ev.is_final]
        assert len(finals) == 1, f"Expected exactly one terminal final; got: {events}"
        assert finals[0].data.get("text") == "alpha done"

        errors = [ev for ev in events if ev.is_error]
        assert errors == [], (
            f"Expected no surfaced error (recovered via decompose); got: {errors}"
        )

    async def test_adapt_loop_limit_still_decomposes_and_recovers(self) -> None:
        """loop_limit (iteration budget exhausted, runtime healthy) is
        decomposable — the direct attempt fails, ADaPT decomposes, and the
        sub-step runs and recovers to a single terminal success."""
        from swarmline.runtime.thin.kernels.adapt import ADaPTKernel

        decompose_plan = json.dumps(
            {
                "type": "plan",
                "goal": "recover from failure",
                "steps": [{"id": "s1", "title": "Sub Alpha", "mode": "react"}],
                "final_format": "",
            }
        )
        call_count = 0

        async def llm_call(messages: Any, prompt: Any, **kw: Any) -> str:
            nonlocal call_count
            call_count += 1
            if '"type": "plan"' in prompt:
                return decompose_plan
            if "Sub Alpha" in prompt:
                return json.dumps({"type": "final", "final_message": "alpha done"})
            # top-level direct attempt: a tool_call that never resolves to a
            # final -> exactly one iteration, then run_react's own
            # loop_limit guard fires (max_iterations=1).
            return json.dumps(
                {
                    "type": "tool_call",
                    "tool": {"name": "noop", "args": {}, "correlation_id": "c1"},
                    "assistant_message": "",
                }
            )

        config = RuntimeConfig(runtime_name="thin", max_iterations=1)
        ctx = _make_context(llm_call=llm_call, config=config)
        kernel = ADaPTKernel()
        events = [ev async for ev in kernel.run(ctx)]

        assert call_count == 3, (
            f"Expected 3 llm_call invocations (loop_limit direct attempt, "
            f"decompose, Sub Alpha); got {call_count}"
        )

        status_texts = [ev.text for ev in events if ev.type == "status"]
        assert any("decompos" in t.lower() for t in status_texts), (
            f"Expected loop_limit to still trigger decomposition; got: {status_texts}"
        )

        finals = [ev for ev in events if ev.is_final]
        assert len(finals) == 1, f"Expected exactly one terminal final; got: {events}"
        assert finals[0].data.get("text") == "alpha done"

        errors = [ev for ev in events if ev.is_error]
        assert errors == [], (
            f"Expected no surfaced error (recovered via decompose); got: {errors}"
        )


# ===========================================================================
# MAJOR 2 (GPT-5.5 review round 2, VERIFY-gate) — cancellation must be
# honored in the gap between the failed direct attempt and the decompose
# ``ctx.llm_call``: a checkpoint firing right before decompose must skip the
# decompose call entirely (distinct from the earlier, already-fixed MAJOR 2
# — sub-step context chaining — documented below).
# ===========================================================================


class TestADaPTChecksCheckpointBeforeDecompose:
    async def test_adapt_cancel_between_direct_failure_and_decompose_skips_decompose(
        self,
    ) -> None:
        """A checkpoint that is clean (returns None) throughout the direct
        attempt but flips to a ``cancelled`` terminal event exactly when
        polled again — right before the decompose ``ctx.llm_call`` — must
        skip decomposition entirely: the cancelled event is surfaced and the
        decompose ``llm_call`` count does NOT increase.

        The direct attempt (invalid JSON, ``max_model_retries=0``) polls the
        checkpoint exactly twice inside ``run_react`` before yielding its own
        terminal ``bad_model_output`` (empirically verified against
        ``run_react`` directly) — both of those polls must see ``None`` so
        the direct attempt itself completes normally; only the THIRD poll
        (``_decompose``'s pre-``llm_call`` checkpoint) must see the flip.
        """
        from swarmline.runtime.thin.kernels.adapt import ADaPTKernel
        from swarmline.runtime.thin.runtime_support import cancelled_event

        call_count = 0
        checkpoint_calls = 0

        class _CancelledToken:
            is_cancelled = True

        async def checkpoint() -> RuntimeEvent | None:
            nonlocal checkpoint_calls
            checkpoint_calls += 1
            if checkpoint_calls <= 2:
                return None
            return cancelled_event(_CancelledToken())

        async def llm_call(messages: Any, prompt: Any, **kw: Any) -> str:
            nonlocal call_count
            call_count += 1
            if '"type": "plan"' in prompt:
                return json.dumps({"type": "final", "final_message": "should not run"})
            # top-level direct attempt: unparseable -> bad_model_output,
            # completing normally BEFORE the checkpoint flips.
            return "{not valid json}"

        config = RuntimeConfig(runtime_name="thin", max_model_retries=0)
        ctx = _make_context(llm_call=llm_call, config=config, checkpoint=checkpoint)
        kernel = ADaPTKernel()
        events = [ev async for ev in kernel.run(ctx)]

        assert call_count == 1, (
            "Cancellation right before decompose must skip the decompose "
            f"llm_call entirely; got {call_count} calls (expected only the "
            "direct attempt's)"
        )

        errors = [ev for ev in events if ev.is_error]
        assert len(errors) == 1, f"Expected exactly one terminal error; got: {events}"
        assert errors[0].data.get("kind") == "cancelled", (
            f"Expected the surfaced error to be the cancellation, not the "
            f"direct attempt's bad_model_output; got: {errors[0].data}"
        )

        finals = [ev for ev in events if ev.is_final]
        assert finals == [], "No success should be reported when cancelled"


# ===========================================================================
# MAJOR 2 (VERIFY-gate) — sibling sub-steps must chain context, mirroring
# run_planner's step_results/step_context threading (planner_strategy.py).
# ===========================================================================


class TestADaPTChainsSubStepContext:
    async def test_adapt_second_sub_step_prompt_includes_first_sub_step_result(
        self,
    ) -> None:
        """Sub-step 2 (Sub Beta)'s prompt must contain Sub Alpha's result text
        — siblings must see each other's outcomes, not just a static
        "Parent step: ..." context repeated for every sub-step."""
        from swarmline.runtime.thin.kernels.adapt import ADaPTKernel

        decompose_plan = json.dumps(
            {
                "type": "plan",
                "goal": "recover from failure",
                "steps": [
                    {"id": "s1", "title": "Sub Alpha", "mode": "react"},
                    {"id": "s2", "title": "Sub Beta", "mode": "react"},
                ],
                "final_format": "",
            }
        )
        beta_prompts: list[str] = []

        async def llm_call(messages: Any, prompt: Any, **kw: Any) -> str:
            if '"type": "plan"' in prompt:
                return decompose_plan
            if "Sub Alpha" in prompt:
                return json.dumps(
                    {"type": "final", "final_message": "alpha result text"}
                )
            if "Sub Beta" in prompt:
                beta_prompts.append(prompt)
                return json.dumps({"type": "final", "final_message": "beta done"})
            return "{not valid json}"

        config = RuntimeConfig(runtime_name="thin", max_model_retries=0)
        ctx = _make_context(llm_call=llm_call, config=config)
        kernel = ADaPTKernel()
        events = [ev async for ev in kernel.run(ctx)]

        assert beta_prompts, "Expected at least one llm_call routed to Sub Beta"
        assert any("alpha result text" in p for p in beta_prompts), (
            "Expected Sub Beta's prompt to carry Sub Alpha's chained result "
            f"text; got: {beta_prompts}"
        )

        finals = [ev for ev in events if ev.is_final]
        assert len(finals) == 1, f"Expected exactly one terminal final; got: {events}"


# ===========================================================================
# MAJOR 3 (VERIFY-gate) — the terminal final's new_messages must accumulate
# ALL executed sub-steps' messages (not just the last one's), matching what
# agent/conversation.py extends self._history with.
# ===========================================================================


class TestADaPTAccumulatesNewMessagesAcrossSubSteps:
    async def test_adapt_final_new_messages_includes_both_sub_steps_in_order(
        self,
    ) -> None:
        """After a successful decomposition (failed direct attempt -> 2
        sub-steps), the terminal final's new_messages must include BOTH
        sub-steps' messages, in order — not just Sub Beta's (the last)."""
        from swarmline.runtime.thin.kernels.adapt import ADaPTKernel

        decompose_plan = json.dumps(
            {
                "type": "plan",
                "goal": "recover from failure",
                "steps": [
                    {"id": "s1", "title": "Sub Alpha", "mode": "react"},
                    {"id": "s2", "title": "Sub Beta", "mode": "react"},
                ],
                "final_format": "",
            }
        )

        async def llm_call(messages: Any, prompt: Any, **kw: Any) -> str:
            if '"type": "plan"' in prompt:
                return decompose_plan
            if "Sub Alpha" in prompt:
                return json.dumps({"type": "final", "final_message": "alpha done"})
            if "Sub Beta" in prompt:
                return json.dumps({"type": "final", "final_message": "beta done"})
            return "{not valid json}"

        config = RuntimeConfig(runtime_name="thin", max_model_retries=0)
        ctx = _make_context(llm_call=llm_call, config=config)
        kernel = ADaPTKernel()
        events = [ev async for ev in kernel.run(ctx)]

        finals = [ev for ev in events if ev.is_final]
        assert len(finals) == 1, f"Expected exactly one terminal final; got: {events}"

        new_messages = finals[0].data.get("new_messages", [])
        contents = [m.get("content", "") for m in new_messages]
        assert any("alpha done" in c for c in contents), (
            f"Expected Sub Alpha's message in accumulated new_messages; got: {contents}"
        )
        assert any("beta done" in c for c in contents), (
            f"Expected Sub Beta's message in accumulated new_messages; got: {contents}"
        )
        alpha_idx = next(i for i, c in enumerate(contents) if "alpha done" in c)
        beta_idx = next(i for i, c in enumerate(contents) if "beta done" in c)
        assert alpha_idx < beta_idx, (
            f"Expected Sub Alpha's message before Sub Beta's; got: {contents}"
        )


# ===========================================================================
# WARNING (VERIFY-gate, cheap) — _decompose failure paths must surface a
# terminal error (no hang, no silent success).
# ===========================================================================


class TestADaPTDecomposeFailurePaths:
    async def test_adapt_decompose_llm_error_surfaces_as_error(self) -> None:
        """ctx.llm_call raising ThinLlmError during _decompose is surfaced as
        that exact terminal error (no hang, no silent success)."""
        from swarmline.runtime.thin.errors import ThinLlmError
        from swarmline.runtime.thin.kernels.adapt import ADaPTKernel
        from swarmline.runtime.types import RuntimeErrorData

        async def llm_call(messages: Any, prompt: Any, **kw: Any) -> str:
            if '"type": "plan"' in prompt:
                raise ThinLlmError(
                    RuntimeErrorData(
                        kind="runtime_crash", message="decompose call failed"
                    )
                )
            # Top-level direct attempt: unparseable -> forces decompose.
            return "{not valid json}"

        config = RuntimeConfig(runtime_name="thin", max_model_retries=0)
        ctx = _make_context(llm_call=llm_call, config=config)
        kernel = ADaPTKernel()
        events = [ev async for ev in kernel.run(ctx)]

        errors = [ev for ev in events if ev.is_error]
        assert len(errors) == 1, f"Expected exactly one terminal error; got: {events}"
        assert errors[0].data.get("kind") == "runtime_crash"
        assert errors[0].data.get("message") == "decompose call failed"

        finals = [ev for ev in events if ev.is_final]
        assert finals == [], (
            "No success should be reported when decompose's llm_call fails"
        )

    async def test_adapt_decompose_invalid_plan_surfaces_bad_model_output(self) -> None:
        """An unparseable/schema-invalid decompose response (parse_plan ->
        None) surfaces a bad_model_output error — no hang, no silent
        success."""
        from swarmline.runtime.thin.kernels.adapt import ADaPTKernel

        async def llm_call(messages: Any, prompt: Any, **kw: Any) -> str:
            if '"type": "plan"' in prompt:
                # Valid JSON, but fails PlanSchema validation (missing
                # required "steps") -> parse_plan returns None.
                return json.dumps({"type": "plan", "goal": "still failing"})
            return "{not valid json}"

        config = RuntimeConfig(runtime_name="thin", max_model_retries=0)
        ctx = _make_context(llm_call=llm_call, config=config)
        kernel = ADaPTKernel()
        events = [ev async for ev in kernel.run(ctx)]

        errors = [ev for ev in events if ev.is_error]
        assert len(errors) == 1, f"Expected exactly one terminal error; got: {events}"
        assert errors[0].data.get("kind") == "bad_model_output"
        assert "decompose" in errors[0].data.get("message", "").lower()

        finals = [ev for ev in events if ev.is_final]
        assert finals == [], (
            "No success should be reported when the decompose response is invalid"
        )


# ===========================================================================
# Registration / contract (registry lives at kernel-patterns Task 3 scope)
# ===========================================================================


class TestADaPTRegistration:
    def test_adapt_registered_and_selectable_by_mode(self) -> None:
        """'adapt' is a live registry mode resolving to an ExecutionKernel."""
        from swarmline.protocols.kernel import ExecutionKernel
        from swarmline.runtime.thin.kernels import get_default_kernel_registry

        registry = get_default_kernel_registry()
        assert "adapt" in registry.modes()

        kernel = registry.get("adapt")
        assert isinstance(kernel, ExecutionKernel)
